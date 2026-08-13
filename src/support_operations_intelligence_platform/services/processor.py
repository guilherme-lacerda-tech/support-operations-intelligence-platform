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


class EventProcessor:
    def __init__(self, session: Session):
        self.session = session
        self.rules = RuleEngine(session)

    def process(self, payload: EventCreate) -> tuple[OperationalEvent, Incident | None, Action | None, str | None]:
        asset = self.session.scalar(select(Asset).where(Asset.external_id == payload.asset_external_id))
        if asset is None:
            raise UnknownAssetError(payload.asset_external_id)

        event = OperationalEvent(
            asset_id=asset.id,
            source=payload.source,
            category=payload.category,
            severity=payload.severity,
            message=payload.message,
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

        action = Action(
            incident_id=incident.id,
            action_type=rule.action_type,
            detail="queued by rule engine",
        )
        self.session.add(action)
        self._audit("incident_created", "incident", incident.id, incident.summary)
        self.session.flush()
        return event, incident, action, None

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

    def _audit(self, event_type: str, entity_type: str, entity_id: int, message: str) -> None:
        self.session.add(
            AuditLog(
                event_type=event_type,
                entity_type=entity_type,
                entity_id=entity_id,
                message=message,
            )
        )

