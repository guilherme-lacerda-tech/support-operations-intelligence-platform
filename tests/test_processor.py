from datetime import UTC, datetime, timedelta

import pytest

from support_operations_intelligence_platform.core.database import create_session_factory
from support_operations_intelligence_platform.cli import run_demo
from support_operations_intelligence_platform.models import Action, AuditLog, Incident, IncidentState
from support_operations_intelligence_platform.schemas import EventCreate
from support_operations_intelligence_platform.seed import seed_demo_data
from support_operations_intelligence_platform.services.actions import execute_action_with_retry
from support_operations_intelligence_platform.services.jobs import run_health_sweep
from support_operations_intelligence_platform.services.processor import EventProcessor, UnknownAssetError


@pytest.fixture()
def session():
    factory = create_session_factory("sqlite:///:memory:")
    db = factory()
    seed_demo_data(db)
    try:
        yield db
    finally:
        db.close()


def test_event_matching_rule_creates_incident_and_action(session):
    payload = EventCreate(
        asset_external_id="PUMP-101",
        source="north-gateway",
        category="offline",
        severity=88,
        message="Heartbeat missing for a synthetic device",
    )

    event, incident, action, skipped = EventProcessor(session).process(payload)

    assert event.id is not None
    assert incident is not None
    assert action is not None
    assert skipped is None
    assert incident.summary.startswith("Offline device triage")


def test_normal_event_is_recorded_without_incident(session):
    payload = EventCreate(
        asset_external_id="PUMP-101",
        source="north-gateway",
        category="offline",
        severity=12,
        message="Minor synthetic telemetry delay",
    )

    _event, incident, action, skipped = EventProcessor(session).process(payload)

    assert incident is None
    assert action is None
    assert skipped == "normal"


def test_warning_event_creates_incident_without_action(session):
    payload = EventCreate(
        asset_id="PUMP-101",
        source="north-gateway",
        category="offline",
        severity=65,
        message="Synthetic warning event for review",
    )

    _event, incident, action, skipped = EventProcessor(session).process(payload)

    assert incident is not None
    assert action is None
    assert skipped == "warning_no_action"


def test_unknown_asset_is_rejected(session):
    payload = EventCreate(
        asset_external_id="UNKNOWN-1",
        source="north-gateway",
        category="offline",
        severity=90,
        message="Unknown synthetic device",
    )

    with pytest.raises(UnknownAssetError):
        EventProcessor(session).process(payload)


def test_cooldown_suppresses_repeated_action(session):
    payload = EventCreate(
        asset_external_id="PUMP-101",
        source="north-gateway",
        category="offline",
        severity=90,
        message="First synthetic outage",
    )
    EventProcessor(session).process(payload)

    _event, incident, action, skipped = EventProcessor(session).process(
        payload.model_copy(update={"message": "Repeated synthetic outage"})
    )

    assert incident is None
    assert action is None
    assert skipped == "cooldown"


def test_cooldown_is_limited_to_same_asset_and_category(session):
    first = EventCreate(
        asset_id="PUMP-101",
        source="north-gateway",
        category="offline",
        severity=90,
        message="First synthetic outage",
    )
    EventProcessor(session).process(first)

    _event, incident, action, skipped = EventProcessor(session).process(
        first.model_copy(update={"category": "battery_low", "message": "Different synthetic category"})
    )

    assert incident is not None
    assert action is not None
    assert skipped is None


def test_action_retry_recovers_from_transient_failure(session):
    _event, _incident, action, _skipped = EventProcessor(session).process(
        EventCreate(
            asset_external_id="GATEWAY-7",
            source="warehouse",
            category="offline",
            severity=91,
            message="Synthetic gateway offline",
        )
    )
    assert action is not None
    action.detail = "fail_once"

    executed = execute_action_with_retry(session, action, max_attempts=3)

    assert executed.state == "succeeded"
    assert executed.attempts == 2


def test_action_retry_marks_failed_after_timeout(session):
    _event, _incident, action, _skipped = EventProcessor(session).process(
        EventCreate(
            asset_external_id="SENSOR-44",
            source="cold-room",
            category="battery_low",
            severity=90,
            message="Synthetic battery is below threshold",
        )
    )
    assert action is not None

    def timeout_transport(_action, _timeout):
        raise TimeoutError("synthetic timeout")

    executed = execute_action_with_retry(
        session,
        action,
        max_attempts=2,
        transport=timeout_transport,
    )

    assert executed.state == "failed"
    assert executed.attempts == 2
    assert "timeout" in executed.detail


def test_permanent_failure_marks_final_failure(session):
    _event, _incident, action, _skipped = EventProcessor(session).process(
        EventCreate(
            asset_id="SENSOR-44",
            source="cold-room",
            category="battery_low",
            severity=90,
            message="Synthetic permanent executor failure",
            executor_mode="permanent_failure",
        )
    )
    assert action is not None

    executed = execute_action_with_retry(session, action, max_attempts=3)

    assert executed.id == action.id
    assert executed.state == "failed"
    assert executed.attempts == 3
    assert session.query(AuditLog).filter(AuditLog.event_type == "action_failed_final").count() == 1


def test_audit_trail_records_event_incident_action_and_execution(session):
    _event, _incident, action, _skipped = EventProcessor(session).process(
        EventCreate(
            asset_id="PUMP-101",
            source="north-gateway",
            category="offline",
            severity=90,
            message="Synthetic critical event for audit",
        )
    )
    assert action is not None
    execute_action_with_retry(session, action)

    event_types = {row.event_type for row in session.query(AuditLog).all()}

    assert {"event_recorded", "incident_created", "action_queued", "action_succeeded"} <= event_types


def test_persistence_after_reopen(tmp_path):
    db_path = tmp_path / "ops.sqlite3"
    factory = create_session_factory(f"sqlite:///{db_path.as_posix()}")
    session = factory()
    try:
        seed_demo_data(session)
        EventProcessor(session).process(
            EventCreate(
                asset_id="PUMP-101",
                source="north-gateway",
                category="offline",
                severity=90,
                message="Synthetic persisted event",
            )
        )
        session.commit()
    finally:
        session.close()

    reopened = create_session_factory(f"sqlite:///{db_path.as_posix()}")()
    try:
        assert reopened.query(Incident).count() == 1
        assert reopened.query(Action).count() == 1
    finally:
        reopened.close()


def test_health_sweep_queues_follow_up_for_stale_open_incident(session):
    payload = EventCreate(
        asset_external_id="PUMP-101",
        source="north-gateway",
        category="offline",
        severity=88,
        message="Heartbeat missing for a synthetic device",
    )
    _event, incident, _action, _skipped = EventProcessor(session).process(payload)
    assert incident is not None
    incident.created_at = datetime.now(UTC) - timedelta(minutes=45)
    session.commit()

    actions_created = run_health_sweep(session, stale_minutes=30)

    assert actions_created == 1


def test_health_sweep_ignores_resolved_incident(session):
    payload = EventCreate(
        asset_external_id="PUMP-101",
        source="north-gateway",
        category="offline",
        severity=88,
        message="Heartbeat missing for a synthetic device",
    )
    _event, incident, _action, _skipped = EventProcessor(session).process(payload)
    assert incident is not None
    incident.created_at = datetime.now(UTC) - timedelta(minutes=45)
    incident.state = IncidentState.RESOLVED.value
    session.commit()

    assert run_health_sweep(session, stale_minutes=30) == 0
    assert session.query(Incident).count() == 1


def test_cli_demo_returns_summary():
    result = run_demo()

    assert result == {
        "assets": 3,
        "incidents": 1,
        "actions": 1,
        "action_state": "succeeded",
    }
