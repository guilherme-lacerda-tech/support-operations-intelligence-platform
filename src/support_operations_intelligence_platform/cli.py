from support_operations_intelligence_platform.core.database import create_session_factory
from support_operations_intelligence_platform.models import Asset
from support_operations_intelligence_platform.schemas import EventCreate
from support_operations_intelligence_platform.seed import seed_demo_data
from support_operations_intelligence_platform.services.actions import execute_action_with_retry
from support_operations_intelligence_platform.services.processor import EventProcessor


def run_demo() -> dict[str, int | str | None]:
    factory = create_session_factory("sqlite:///:memory:")
    session = factory()
    try:
        seed_demo_data(session)
        payload = EventCreate(
            asset_external_id="PUMP-101",
            source="north-gateway",
            category="offline",
            severity=88,
            message="Heartbeat missing for the synthetic pump controller",
        )
        _event, incident, action, _reason = EventProcessor(session).process(payload)
        if action:
            execute_action_with_retry(session, action)
        session.commit()
        return {
            "assets": session.query(Asset).count(),
            "incidents": 1 if incident else 0,
            "actions": 1 if action else 0,
            "action_state": action.state if action else None,
        }
    finally:
        session.close()


def main() -> None:
    print(run_demo())


if __name__ == "__main__":
    main()
