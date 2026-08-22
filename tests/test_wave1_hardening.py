from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text

from support_operations_intelligence_platform.api.app import create_app
from support_operations_intelligence_platform.core.database import build_engine, create_session_factory
from support_operations_intelligence_platform.models import Action, ActionState, CheckState, IdempotencyRecord
from support_operations_intelligence_platform.schemas import EventCreate
from support_operations_intelligence_platform.seed import seed_demo_data
from support_operations_intelligence_platform.services.actions import ActionWorker
from support_operations_intelligence_platform.services.checks import (
    InvalidCheckTransition,
    create_check,
    expire_waiting_checks,
    transition_check,
)
from support_operations_intelligence_platform.services.processor import EventProcessor


def sqlite_url(path) -> str:
    return f"sqlite:///{path.as_posix()}"


def critical_payload(**updates) -> EventCreate:
    data = {
        "asset_external_id": "PUMP-101",
        "source": "north-gateway",
        "category": "offline",
        "severity": 92,
        "message": "Synthetic heartbeat failure detected",
        "executor_mode": "success",
    }
    data.update(updates)
    return EventCreate(**data)


def test_concurrent_idempotency_key_reuses_single_processing_result(tmp_path):
    factory = create_session_factory(sqlite_url(tmp_path / "idempotency.sqlite3"))
    seed_session = factory()
    seed_demo_data(seed_session)
    seed_session.close()

    payload = critical_payload(idempotency_key="intent-demo-0001")

    def ingest_once():
        session = factory()
        try:
            event, incident, action, skipped, replay = EventProcessor(session).process(payload)
            session.commit()
            return {
                "event_id": event.id,
                "incident_id": incident.id if incident else None,
                "action_id": action.id if action else None,
                "skipped": skipped,
                "replay": replay,
            }
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=100) as executor:
        results = list(executor.map(lambda _: ingest_once(), range(100)))

    session = factory()
    try:
        assert len({result["event_id"] for result in results}) == 1
        assert len({result["incident_id"] for result in results}) == 1
        assert len({result["action_id"] for result in results}) == 1
        assert sum(result["replay"] for result in results) == 99
        record = session.query(IdempotencyRecord).one()
        assert record.hits == 99
        assert session.query(Action).count() == 1
    finally:
        session.close()


def test_api_idempotency_response_marks_replay(tmp_path):
    factory = create_session_factory(sqlite_url(tmp_path / "api-idempotency.sqlite3"))
    seed_session = factory()
    seed_demo_data(seed_session)
    seed_session.close()
    client = TestClient(create_app(factory))
    payload = critical_payload(idempotency_key="intent-api-0001").model_dump()

    first = client.post("/events", json=payload)
    second = client.post("/events", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["event"]["id"] == second.json()["event"]["id"]
    assert first.json()["idempotent_replay"] is False
    assert second.json()["idempotent_replay"] is True
    assert client.get("/metrics").json()["idempotency_hits"] == 1


def test_persistent_worker_processes_queued_action_after_restart(tmp_path):
    factory = create_session_factory(sqlite_url(tmp_path / "worker-restart.sqlite3"))
    session = factory()
    seed_demo_data(session)
    _event, _incident, action, _skipped, _replay = EventProcessor(session).process(critical_payload())
    assert action is not None
    action_id = action.id
    session.commit()
    session.close()

    result = ActionWorker(factory, timeout_seconds=0.001).run_once()
    reopened = factory()
    try:
        action = reopened.get(Action, action_id)
        assert result["processed"] == 1
        assert action is not None
        assert action.state == ActionState.SUCCEEDED.value
    finally:
        reopened.close()


def test_retry_pending_survives_restart_and_succeeds(tmp_path):
    factory = create_session_factory(sqlite_url(tmp_path / "retry-restart.sqlite3"))
    session = factory()
    seed_demo_data(session)
    _event, _incident, action, _skipped, _replay = EventProcessor(session).process(
        critical_payload(asset_external_id="GATEWAY-7", executor_mode="transient_then_success")
    )
    assert action is not None
    action_id = action.id
    session.commit()
    session.close()

    first = ActionWorker(factory, timeout_seconds=0.001, retry_delay_seconds=0).run_once()
    second = ActionWorker(factory, timeout_seconds=0.001, retry_delay_seconds=0).run_once()

    reopened = factory()
    try:
        action = reopened.get(Action, action_id)
        assert first["retried"] == 1
        assert second["succeeded"] == 1
        assert action is not None
        assert action.state == ActionState.SUCCEEDED.value
        assert action.attempts == 2
    finally:
        reopened.close()


def test_stale_lease_recovers_without_duplicate_action(tmp_path):
    factory = create_session_factory(sqlite_url(tmp_path / "stale-lease.sqlite3"))
    session = factory()
    seed_demo_data(session)
    _event, _incident, action, _skipped, _replay = EventProcessor(session).process(critical_payload())
    assert action is not None
    action.lease_id = "dead-worker"
    action.leased_at = datetime.now(UTC) - timedelta(minutes=5)
    action_id = action.id
    session.commit()
    session.close()

    result = ActionWorker(factory, timeout_seconds=0.001, lease_seconds=10).run_once()
    reopened = factory()
    try:
        assert result["processed"] == 1
        assert reopened.query(Action).count() == 1
        assert reopened.get(Action, action_id).state == ActionState.SUCCEEDED.value
    finally:
        reopened.close()


def test_check_state_machine_persists_timeout_after_restart(tmp_path):
    factory = create_session_factory(sqlite_url(tmp_path / "checks.sqlite3"))
    session = factory()
    now = datetime(2026, 1, 1, tzinfo=UTC)
    check = create_check(session, name="synthetic phase check", asset_external_id="PUMP-101", now=now)
    transition_check(session, check, CheckState.STARTED.value, now=now)
    transition_check(
        session,
        check,
        CheckState.WAITING_CONFIRMATION.value,
        timeout_seconds=30,
        now=now,
    )
    session.commit()
    session.close()

    reopened = factory()
    try:
        assert expire_waiting_checks(reopened, now=now + timedelta(seconds=31)) == 1
        reopened.commit()
    finally:
        reopened.close()

    final_session = factory()
    try:
        stored = final_session.query(type(check)).one()
        assert stored.state == CheckState.TIMEOUT.value
    finally:
        final_session.close()


def test_invalid_check_transition_fails():
    factory = create_session_factory("sqlite:///:memory:")
    session = factory()
    check = create_check(session, name="synthetic phase check", asset_external_id="PUMP-101")

    with pytest.raises(InvalidCheckTransition):
        transition_check(session, check, CheckState.CONFIRMED.value)

    session.close()


def test_backpressure_rejects_action_without_silently_growing_queue(monkeypatch):
    class TinyQueueSettings:
        max_queue_backlog = 0

    import support_operations_intelligence_platform.services.processor as processor_module

    monkeypatch.setattr(processor_module, "get_settings", lambda: TinyQueueSettings())
    factory = create_session_factory("sqlite:///:memory:")
    session = factory()
    seed_demo_data(session)

    _event, incident, action, skipped, _replay = EventProcessor(session).process(critical_payload())

    assert incident is not None
    assert action is None
    assert skipped == "queue_backpressure"
    session.close()


def test_migration_adds_wave1_columns_to_existing_sqlite_database(tmp_path):
    db_url = sqlite_url(tmp_path / "old-schema.sqlite3")
    engine = build_engine(db_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE operational_events (
                    id INTEGER PRIMARY KEY,
                    asset_id INTEGER NOT NULL,
                    source VARCHAR(120) NOT NULL,
                    category VARCHAR(80) NOT NULL,
                    severity INTEGER NOT NULL,
                    message TEXT NOT NULL,
                    created_at DATETIME NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE actions (
                    id INTEGER PRIMARY KEY,
                    incident_id INTEGER NOT NULL,
                    action_type VARCHAR(80) NOT NULL,
                    state VARCHAR(40) NOT NULL,
                    attempts INTEGER NOT NULL,
                    detail TEXT NOT NULL,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                )
                """
            )
        )
    engine.dispose()

    factory = create_session_factory(db_url)
    factory().close()
    upgraded = build_engine(db_url)
    inspector = inspect(upgraded)
    event_columns = {column["name"] for column in inspector.get_columns("operational_events")}
    action_columns = {column["name"] for column in inspector.get_columns("actions")}

    assert "correlation_id" in event_columns
    assert {"next_attempt_at", "lease_id", "leased_at"}.issubset(action_columns)
