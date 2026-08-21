from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from support_operations_intelligence_platform.models import (
    Action,
    Asset,
    AuditLog,
    Incident,
    IncidentState,
    OperationalEvent,
)
from support_operations_intelligence_platform.schemas import EventCreate
from support_operations_intelligence_platform.services.rules import RuleEngine


class UnknownAssetError(ValueError):
    pass


WARNING_SEVERITY = 50
CRITICAL_SEVERITY = 80
DEFAULT_COOLDOWN_MINUTES = 20
DEFAULT_ACTION_TYPE = "create_ticket"


class EventProcessor:
    def __init__(self, session: Session):
        self.session = session
        self.rules = RuleEngine(session)

    def process(self, payload: EventCreate) -> tuple[OperationalEvent, Incident | None, Action | None, str | None]:
        asset_key = payload.asset_external_id or payload.asset_id
        asset = self.session.scalar(select(Asset).where(Asset.external_id == asset_key))
        if asset is None:
            raise UnknownAssetError(asset_key or "")

        occurred_at = self._as_utc(payload.occurred_at)

        event = OperationalEvent(
            asset_id=asset.id,
            source=payload.source,
            category=payload.category,
            severity=payload.severity,
            message=payload.message,
            occurred_at=occurred_at,
            executor_mode=payload.executor_mode,
        )
        asset.status = payload.category
        self.session.add(event)
        self.session.flush()
        self._audit("event_recorded", "operational_event", event.id, self._event_audit_message(event))

        if event.severity < WARNING_SEVERITY:
            return event, None, None, "normal"

        rule = self.rules.match(event)
        cooldown_minutes = rule.cooldown_minutes if rule else DEFAULT_COOLDOWN_MINUTES
        if self._in_cooldown(asset, event.category, occurred_at, cooldown_minutes):
            self._audit(
                "event_suppressed",
                "operational_event",
                event.id,
                "Cooldown suppressed duplicate incident/action for same asset and category",
            )
            return event, None, None, "cooldown"

        incident = Incident(
            asset_id=asset.id,
            rule_id=rule.id if rule else None,
            event_id=event.id,
            category=event.category,
            state=IncidentState.OPEN.value,
            summary=self._incident_summary(asset, event, rule.name if rule else None),
            created_at=occurred_at,
            updated_at=occurred_at,
        )
        self.session.add(incident)
        self.session.flush()

        action = None
        if event.severity >= CRITICAL_SEVERITY:
            action = Action(
                incident_id=incident.id,
                action_type=rule.action_type if rule else DEFAULT_ACTION_TYPE,
                detail=f"executor_mode={event.executor_mode}",
                created_at=occurred_at,
                updated_at=occurred_at,
            )
            self.session.add(action)
            self.session.flush()
            self._audit("action_queued", "action", action.id, "Critical event queued follow-up action")

        self._audit("incident_created", "incident", incident.id, incident.summary)
        self.session.flush()
        if action is not None:
            return event, incident, action, None
        return event, incident, None, "warning_no_action"

    def _in_cooldown(
        self,
        asset: Asset,
        category: str,
        occurred_at: datetime,
        cooldown_minutes: int,
    ) -> bool:
        if cooldown_minutes <= 0:
            return False
        threshold = occurred_at - timedelta(minutes=cooldown_minutes)
        statement = (
            select(Incident)
            .where(Incident.asset_id == asset.id)
            .where(Incident.category == category)
            .where(Incident.created_at >= threshold)
            .where(Incident.state != IncidentState.RESOLVED.value)
        )
        return self.session.scalars(statement).first() is not None

    def _audit(self, event_type: str, entity_type: str, entity_id: int, message: str) -> None:
        self.session.add(
            AuditLog(
                event_type=event_type,
                entity_type=entity_type,
                entity_id=entity_id,
                message=message,
            )
        )

    @staticmethod
    def _as_utc(value: datetime | None) -> datetime:
        if value is None:
            return datetime.now(UTC)
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @staticmethod
    def _event_audit_message(event: OperationalEvent) -> str:
        if event.severity < WARNING_SEVERITY:
            return "Normal event persisted without incident/action"
        if event.severity < CRITICAL_SEVERITY:
            return "Warning event persisted for incident review"
        return "Critical event persisted for incident/action evaluation"

    @staticmethod
    def _incident_summary(asset: Asset, event: OperationalEvent, rule_name: str | None) -> str:
        prefix = rule_name or "Synthetic severity policy"
        level = "critical" if event.severity >= CRITICAL_SEVERITY else "warning"
        return f"{prefix}: {asset.external_id} reported {level} {event.category}"

