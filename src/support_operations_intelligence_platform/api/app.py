from collections.abc import Iterator

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from support_operations_intelligence_platform.core.database import SessionLocal, create_session_factory
from support_operations_intelligence_platform.models import Action, Asset, AutomationRule, Incident
from support_operations_intelligence_platform.schemas import (
    ActionRead,
    AssetCreate,
    AssetRead,
    EventCreate,
    IncidentRead,
    JobResult,
    ProcessResult,
    RuleCreate,
    RuleRead,
)
from support_operations_intelligence_platform.seed import seed_demo_data
from support_operations_intelligence_platform.services.jobs import run_health_sweep
from support_operations_intelligence_platform.services.processor import EventProcessor, UnknownAssetError


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
            event, incident, action, skipped_reason = EventProcessor(session).process(payload)
        except UnknownAssetError as exc:
            raise HTTPException(status_code=404, detail="asset not found") from exc
        return ProcessResult(event=event, incident=incident, action=action, skipped_reason=skipped_reason)

    @app.get("/incidents", response_model=list[IncidentRead], tags=["incidents"])
    def list_incidents(session: Session = Depends(get_session)) -> list[Incident]:
        return list(session.scalars(select(Incident).order_by(Incident.created_at.desc())).all())

    @app.get("/actions", response_model=list[ActionRead], tags=["actions"])
    def list_actions(session: Session = Depends(get_session)) -> list[Action]:
        return list(session.scalars(select(Action).order_by(Action.created_at.desc())).all())

    @app.post("/jobs/health-sweep", response_model=JobResult, tags=["jobs"])
    def health_sweep(session: Session = Depends(get_session)) -> JobResult:
        actions_created = run_health_sweep(session)
        return JobResult(job_name="health_sweep", status="succeeded", actions_created=actions_created)

    return app


def create_test_app(database_url: str = "sqlite:///:memory:") -> FastAPI:
    return create_app(create_session_factory(database_url))

