from collections.abc import Iterator

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from support_operations_intelligence_platform.core.settings import get_settings
from support_operations_intelligence_platform.core.database import SessionLocal, create_session_factory
from support_operations_intelligence_platform.models import (
    Action,
    ActionState,
    Asset,
    AuditLog,
    AutomationRule,
    CheckRun,
    IdempotencyRecord,
    Incident,
    JobRun,
    OperationalEvent,
)
from support_operations_intelligence_platform.schemas import (
    ActionRead,
    AssetCreate,
    AssetRead,
    CheckCreate,
    CheckRead,
    CheckTransition,
    EventCreate,
    IncidentRead,
    JobResult,
    ProcessResult,
    RuleCreate,
    RuleRead,
)
from support_operations_intelligence_platform.seed import seed_demo_data
from support_operations_intelligence_platform.services.checks import (
    InvalidCheckTransition,
    create_check,
    expire_waiting_checks,
    transition_check,
)
from support_operations_intelligence_platform.services.jobs import run_health_sweep
from support_operations_intelligence_platform.services.processor import EventProcessor, UnknownAssetError
from support_operations_intelligence_platform.services.actions import process_due_actions


def create_app(session_factory: sessionmaker[Session] | None = None) -> FastAPI:
    factory = session_factory or SessionLocal
    app = FastAPI(
        title="Support Operations Intelligence Platform",
        version="0.1.0",
        description="Synthetic operations automation, rule engine and audit platform.",
    )

    def get_session() -> Iterator[Session]:
        session = factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    @app.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready", tags=["health"])
    def ready(session: Session = Depends(get_session)) -> dict[str, int | str]:
        return {"status": "ready", "assets": session.query(Asset).count()}

    @app.post("/demo/seed", tags=["demo"])
    def seed(session: Session = Depends(get_session)) -> dict[str, str]:
        seed_demo_data(session)
        return {"status": "seeded"}

    @app.post("/assets", response_model=AssetRead, tags=["assets"])
    def create_asset(payload: AssetCreate, session: Session = Depends(get_session)) -> Asset:
        existing = session.scalar(select(Asset).where(Asset.external_id == payload.external_id))
        if existing:
            raise HTTPException(status_code=409, detail="asset already exists")
        asset = Asset(**payload.model_dump(), status="registered")
        session.add(asset)
        session.flush()
        return asset

    @app.get("/assets", response_model=list[AssetRead], tags=["assets"])
    def list_assets(session: Session = Depends(get_session)) -> list[Asset]:
        return list(session.scalars(select(Asset).order_by(Asset.external_id)).all())

    @app.post("/rules", response_model=RuleRead, tags=["rules"])
    def create_rule(payload: RuleCreate, session: Session = Depends(get_session)) -> AutomationRule:
        rule = AutomationRule(**payload.model_dump())
        session.add(rule)
        session.flush()
        return rule

    @app.get("/rules", response_model=list[RuleRead], tags=["rules"])
    def list_rules(session: Session = Depends(get_session)) -> list[AutomationRule]:
        return list(session.scalars(select(AutomationRule).order_by(AutomationRule.name)).all())

    @app.post("/events", response_model=ProcessResult, tags=["events"])
    def ingest_event(payload: EventCreate, session: Session = Depends(get_session)) -> ProcessResult:
        try:
            event, incident, action, skipped_reason, idempotent_replay = EventProcessor(session).process(payload)
        except UnknownAssetError as exc:
            raise HTTPException(status_code=404, detail="asset not found") from exc
        return ProcessResult(
            event=event,
            incident=incident,
            action=action,
            skipped_reason=skipped_reason,
            idempotency_key=payload.idempotency_key,
            idempotent_replay=idempotent_replay,
        )

    @app.get("/incidents", response_model=list[IncidentRead], tags=["incidents"])
    def list_incidents(session: Session = Depends(get_session)) -> list[Incident]:
        return list(session.scalars(select(Incident).order_by(Incident.created_at.desc())).all())

    @app.get("/actions", response_model=list[ActionRead], tags=["actions"])
    def list_actions(session: Session = Depends(get_session)) -> list[Action]:
        return list(session.scalars(select(Action).order_by(Action.created_at.desc())).all())

    @app.get("/metrics", tags=["metrics"])
    def metrics(session: Session = Depends(get_session)) -> dict[str, float | int]:
        actions = list(session.scalars(select(Action)).all())
        processed_actions = [
            action
            for action in actions
            if action.state in {ActionState.SUCCEEDED.value, ActionState.FAILED.value}
        ]
        latencies = [
            max((action.updated_at - action.created_at).total_seconds(), 0)
            for action in processed_actions
        ]
        retry_attempts = sum(max(action.attempts - 1, 0) for action in actions)
        queue_backlog = sum(
            action.state in {ActionState.QUEUED.value, ActionState.RETRY.value}
            for action in actions
        )
        queued = [action for action in actions if action.state in {ActionState.QUEUED.value, ActionState.RETRY.value}]
        oldest_queued_age = 0.0
        if queued:
            from datetime import UTC, datetime

            current_time = datetime.now(UTC)
            oldest_queued_age = max(
                (
                    current_time
                    - (
                        action.created_at
                        if action.created_at.tzinfo is not None
                        else action.created_at.replace(tzinfo=UTC)
                    )
                ).total_seconds()
                for action in queued
            )
        return {
            "events": session.query(OperationalEvent).count(),
            "events_received": session.query(OperationalEvent).count(),
            "incidents": session.query(Incident).count(),
            "incidents_created": session.query(Incident).count(),
            "actions": session.query(Action).count(),
            "queuedActions": session.query(Action).filter(Action.state == ActionState.QUEUED.value).count(),
            "retryActions": session.query(Action).filter(Action.state == ActionState.RETRY.value).count(),
            "succeededActions": session.query(Action).filter(Action.state == ActionState.SUCCEEDED.value).count(),
            "failedActions": session.query(Action).filter(Action.state == ActionState.FAILED.value).count(),
            "actions_queued": queue_backlog,
            "actions_processed": len(processed_actions),
            "actions_failed": session.query(Action).filter(Action.state == ActionState.FAILED.value).count(),
            "permanentFailures": session.query(Action)
            .filter(Action.state == ActionState.FAILED.value)
            .filter(Action.detail.contains("permanent"))
            .count(),
            "cooldownSuppressions": session.query(AuditLog).filter(AuditLog.event_type == "event_suppressed").count(),
            "cooldown_suppressions": session.query(AuditLog).filter(AuditLog.event_type == "event_suppressed").count(),
            "idempotency_hits": session.query(AuditLog).filter(AuditLog.event_type == "idempotency_hit").count(),
            "queue_backlog": queue_backlog,
            "oldest_queued_item_seconds": round(oldest_queued_age, 3),
            "action_latency_seconds": round(sum(latencies) / len(latencies), 3) if latencies else 0,
            "retryAttempts": int(retry_attempts or 0),
            "retries": int(retry_attempts or 0),
            "auditEntries": session.query(AuditLog).count(),
        }

    @app.post("/maintenance/process-actions", tags=["maintenance"])
    def process_actions(session: Session = Depends(get_session)) -> dict[str, int]:
        settings = get_settings()
        result = process_due_actions(
            session,
            max_attempts=settings.action_max_attempts,
            timeout_seconds=settings.action_timeout_seconds,
            retry_delay_seconds=settings.action_retry_delay_seconds,
            lease_seconds=settings.action_lease_seconds,
        )
        return {
            "processed": result["processed"],
            "succeeded": result["succeeded"],
            "failed": result["failed"],
            "retried": result["retried"],
        }

    @app.post("/checks", response_model=CheckRead, tags=["checks"])
    def create_check_run(payload: CheckCreate, session: Session = Depends(get_session)) -> CheckRun:
        return create_check(
            session,
            name=payload.name,
            asset_external_id=payload.asset_external_id,
            detail=payload.detail,
        )

    @app.post("/checks/{check_id}/transition", response_model=CheckRead, tags=["checks"])
    def transition_check_run(
        check_id: int,
        payload: CheckTransition,
        session: Session = Depends(get_session),
    ) -> CheckRun:
        check = session.get(CheckRun, check_id)
        if check is None:
            raise HTTPException(status_code=404, detail="check not found")
        try:
            return transition_check(
                session,
                check,
                payload.target_state,
                detail=payload.detail,
                timeout_seconds=payload.timeout_seconds,
            )
        except InvalidCheckTransition as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/checks/expire-timeouts", tags=["checks"])
    def expire_check_timeouts(session: Session = Depends(get_session)) -> dict[str, int]:
        return {"expired": expire_waiting_checks(session)}

    @app.get("/audit", tags=["audit"])
    def audit(session: Session = Depends(get_session)) -> list[dict[str, int | str]]:
        rows = session.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(100)).all()
        return [
            {
                "id": row.id,
                "eventType": row.event_type,
                "entityType": row.entity_type,
                "entityId": row.entity_id,
                "message": row.message,
            }
            for row in rows
        ]

    @app.delete("/admin/reset", tags=["admin"])
    def reset_workload(session: Session = Depends(get_session)) -> dict[str, str]:
        for model in (AuditLog, IdempotencyRecord, CheckRun, Action, Incident, OperationalEvent, JobRun):
            session.execute(delete(model))
        return {"status": "reset"}

    @app.post("/jobs/health-sweep", response_model=JobResult, tags=["jobs"])
    def health_sweep(session: Session = Depends(get_session)) -> JobResult:
        actions_created = run_health_sweep(session)
        return JobResult(job_name="health_sweep", status="succeeded", actions_created=actions_created)

    return app


def create_test_app(database_url: str = "sqlite:///:memory:") -> FastAPI:
    return create_app(create_session_factory(database_url))
