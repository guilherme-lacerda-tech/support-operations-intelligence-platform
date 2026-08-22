from datetime import UTC, datetime, timedelta
import logging
from time import sleep
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from support_operations_intelligence_platform.core.settings import get_settings
from support_operations_intelligence_platform.core.structured_logging import log_json
from support_operations_intelligence_platform.models import (
    Action,
    ActionState,
    Asset,
    AuditLog,
    IdempotencyRecord,
    Incident,
    IncidentState,
    OperationalEvent,
)
from support_operations_intelligence_platform.schemas import EventCreate
from support_operations_intelligence_platform.services.rules import RuleEngine


class UnknownAssetError(ValueError):
    pass


logger = logging.getLogger(__name__)


class EventProcessor:
    def __init__(self, session: Session):
        self.session = session
        self.rules = RuleEngine(session)

    def process(
        self,
        payload: EventCreate,
    ) -> tuple[OperationalEvent, Incident | None, Action | None, str | None, bool]:
        if payload.idempotency_key:
            return self._process_with_idempotency(payload)
        event, incident, action, skipped_reason = self._process_new(payload)
        log_json(
            logger,
            "event_processed",
            event_id=event.id,
            incident_id=incident.id if incident is not None else None,
            action_id=action.id if action is not None else None,
            skipped_reason=skipped_reason,
            correlation_id=event.correlation_id,
        )
        return event, incident, action, skipped_reason, False

    def _process_with_idempotency(
        self,
        payload: EventCreate,
    ) -> tuple[OperationalEvent, Incident | None, Action | None, str | None, bool]:
        record = self.session.scalar(
            select(IdempotencyRecord).where(IdempotencyRecord.key == payload.idempotency_key)
        )
        if record is not None and record.event_id is not None:
            return self._replay_idempotent_record(record)

        try:
            with self.session.begin_nested():
                record = IdempotencyRecord(key=payload.idempotency_key)
                self.session.add(record)
                self.session.flush()
        except IntegrityError:
            self.session.rollback()
            return self._wait_for_idempotent_result(payload.idempotency_key)

        event, incident, action, skipped_reason = self._process_new(payload)
        record.event_id = event.id
        record.incident_id = incident.id if incident is not None else None
        record.action_id = action.id if action is not None else None
        record.skipped_reason = skipped_reason
        record.updated_at = datetime.now(UTC)
        self.session.flush()
        log_json(
            logger,
            "event_processed",
            event_id=event.id,
            incident_id=incident.id if incident is not None else None,
            action_id=action.id if action is not None else None,
            skipped_reason=skipped_reason,
            idempotency_key=payload.idempotency_key,
            correlation_id=event.correlation_id,
        )
        return event, incident, action, skipped_reason, False

    def _process_new(self, payload: EventCreate) -> tuple[OperationalEvent, Incident | None, Action | None, str | None]:
        asset = self.session.scalar(select(Asset).where(Asset.external_id == payload.asset_external_id))
        if asset is None:
            raise UnknownAssetError(payload.asset_external_id)

        event = OperationalEvent(
            asset_id=asset.id,
            source=payload.source,
            category=payload.category,
            severity=payload.severity,
            message=payload.message,
            correlation_id=payload.correlation_id or f"corr-{uuid4().hex}",
        )
        asset.status = payload.category
        self.session.add(event)
        self.session.flush()

        rule = self.rules.match(event)
        if rule is None:
            self._audit("event_recorded", "operational_event", event.id, "No rule matched event")
            return event, None, None, "no_matching_rule"

        if self._in_cooldown(asset, rule.cooldown_minutes):
            self._audit("event_suppressed", "operational_event", event.id, "Cooldown suppressed action")
            return event, None, None, "cooldown"

        incident = Incident(
            asset_id=asset.id,
            rule_id=rule.id,
            event_id=event.id,
            state=IncidentState.OPEN.value,
            summary=f"{rule.name}: {asset.external_id} reported {event.category}",
        )
        self.session.add(incident)
        self.session.flush()

        action = None
        if rule.action_type != "none":
            if self._queue_backlog() >= get_settings().max_queue_backlog:
                self._audit("queue_backpressure", "incident", incident.id, "Queue backlog limit rejected action")
                self.session.flush()
                return event, incident, None, "queue_backpressure"
            action = Action(
                incident_id=incident.id,
                action_type=rule.action_type,
                state=ActionState.QUEUED.value,
                detail=payload.executor_mode,
                next_attempt_at=datetime.now(UTC),
            )
            self.session.add(action)
        self._audit("incident_created", "incident", incident.id, incident.summary)
        self.session.flush()
        return event, incident, action, None

    def _replay_idempotent_record(
        self,
        record: IdempotencyRecord,
    ) -> tuple[OperationalEvent, Incident | None, Action | None, str | None, bool]:
        self.session.execute(
            update(IdempotencyRecord)
            .where(IdempotencyRecord.id == record.id)
            .values(hits=IdempotencyRecord.hits + 1, updated_at=datetime.now(UTC))
        )
        self._audit("idempotency_hit", "idempotency_record", record.id, "Reused idempotent event result")
        event = self.session.get(OperationalEvent, record.event_id)
        if event is None:
            raise RuntimeError("idempotency record points to a missing event")
        incident = self.session.get(Incident, record.incident_id) if record.incident_id else None
        action = self.session.get(Action, record.action_id) if record.action_id else None
        self.session.flush()
        log_json(
            logger,
            "idempotency_replay",
            event_id=event.id,
            incident_id=incident.id if incident is not None else None,
            action_id=action.id if action is not None else None,
            idempotency_key=record.key,
            correlation_id=event.correlation_id,
        )
        return event, incident, action, record.skipped_reason, True

    def _wait_for_idempotent_result(
        self,
        idempotency_key: str,
        *,
        attempts: int = 100,
        delay_seconds: float = 0.01,
    ) -> tuple[OperationalEvent, Incident | None, Action | None, str | None, bool]:
        for _ in range(attempts):
            self.session.expire_all()
            record = self.session.scalar(
                select(IdempotencyRecord).where(IdempotencyRecord.key == idempotency_key)
            )
            if record is not None and record.event_id is not None:
                return self._replay_idempotent_record(record)
            sleep(delay_seconds)
        raise TimeoutError("idempotent result was not committed before timeout")

    def _in_cooldown(self, asset: Asset, cooldown_minutes: int) -> bool:
        if cooldown_minutes <= 0:
            return False
        threshold = datetime.now(UTC) - timedelta(minutes=cooldown_minutes)
        statement = (
            select(Incident)
            .where(Incident.asset_id == asset.id)
            .where(Incident.created_at >= threshold)
            .where(Incident.state != IncidentState.RESOLVED.value)
        )
        return self.session.scalars(statement).first() is not None

    def _queue_backlog(self) -> int:
        return self.session.query(Action).filter(Action.state.in_([ActionState.QUEUED.value, ActionState.RETRY.value])).count()

    def _audit(self, event_type: str, entity_type: str, entity_id: int, message: str) -> None:
        self.session.add(
            AuditLog(
                event_type=event_type,
                entity_type=entity_type,
                entity_id=entity_id,
                message=message,
            )
        )
