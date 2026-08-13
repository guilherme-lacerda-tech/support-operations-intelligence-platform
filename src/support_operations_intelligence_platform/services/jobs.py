from datetime import UTC, datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import select
from sqlalchemy.orm import Session

from support_operations_intelligence_platform.models import Action, Incident, IncidentState, JobRun


def run_health_sweep(session: Session, *, stale_minutes: int = 30) -> int:
    threshold = datetime.now(UTC) - timedelta(minutes=stale_minutes)
    open_incidents = session.scalars(
        select(Incident)
        .where(Incident.state == IncidentState.OPEN.value)
        .where(Incident.created_at <= threshold)
    ).all()
    actions_created = 0
    for incident in open_incidents:
        action = Action(
            incident_id=incident.id,
            action_type="follow_up",
            detail=f"health sweep found incident open for at least {stale_minutes} minutes",
        )
        session.add(action)
        actions_created += 1

    session.add(
        JobRun(
            name="health_sweep",
            status="succeeded",
            detail=f"actions_created={actions_created}",
            finished_at=datetime.now(UTC),
        )
    )
    session.flush()
    return actions_created


def build_scheduler(job) -> BackgroundScheduler:
    scheduler = BackgroundScheduler()
    scheduler.add_job(job, "interval", minutes=5, id="health_sweep", replace_existing=True)
    return scheduler

