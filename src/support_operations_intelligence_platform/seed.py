from sqlalchemy.orm import Session

from support_operations_intelligence_platform.models import Asset, AutomationRule


def seed_demo_data(session: Session) -> None:
    if session.query(Asset).count():
        return
    session.add_all(
        [
            Asset(external_id="PUMP-101", name="North pump controller", group="water-treatment"),
            Asset(external_id="GATEWAY-7", name="Warehouse telemetry gateway", group="logistics"),
            Asset(external_id="SENSOR-44", name="Cold room synthetic sensor", group="facilities"),
            AutomationRule(
                name="Offline device triage",
                category="offline",
                minimum_severity=70,
                cooldown_minutes=20,
                action_type="create_ticket",
            ),
            AutomationRule(
                name="Battery warning escalation",
                category="battery_low",
                minimum_severity=80,
                cooldown_minutes=60,
                action_type="notify_owner",
            ),
        ]
    )
    session.commit()

