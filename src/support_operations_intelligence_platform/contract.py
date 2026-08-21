from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from support_operations_intelligence_platform.models import (
    Action,
    ActionState,
    Asset,
    AuditLog,
    Incident,
    OperationalEvent,
)
from support_operations_intelligence_platform.schemas import EventCreate
from support_operations_intelligence_platform.services.actions import execute_action_with_retry
from support_operations_intelligence_platform.services.processor import EventProcessor


def load_workload(path: str | Path) -> list[dict[str, object]]:
    workload_path = Path(path)
    with workload_path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def seed_assets_from_events(session: Session, events: Iterable[dict[str, object]]) -> None:
    asset_ids = sorted({str(event["asset_id"]) for event in events})
    existing = set(session.scalars(select(Asset.external_id)).all())
    new_assets = [
        Asset(external_id=asset_id, name=f"Synthetic asset {asset_id}", group="contract")
        for asset_id in asset_ids
        if asset_id not in existing
    ]
    session.add_all(new_assets)
    session.flush()


def process_contract_events(
    session: Session,
    events: list[dict[str, object]],
    *,
    process_actions: bool = True,
) -> dict[str, int]:
    seed_assets_from_events(session, events)
    processor = EventProcessor(session)
    skipped_counts = {"normal": 0, "warning_no_action": 0, "cooldown": 0}

    for row in events:
        payload = EventCreate(**row)
        _event, _incident, _action, skipped = processor.process(payload)
        if skipped in skipped_counts:
            skipped_counts[skipped] += 1

    if process_actions:
        queued_actions = session.scalars(
            select(Action).where(Action.state == ActionState.QUEUED.value).order_by(Action.id)
        ).all()
        for action in queued_actions:
            execute_action_with_retry(session, action)

    session.flush()
    return canonical_summary(session, skipped_counts)


def canonical_summary(session: Session, skipped_counts: dict[str, int] | None = None) -> dict[str, int]:
    skipped_counts = skipped_counts or {"normal": 0, "warning_no_action": 0, "cooldown": 0}
    actions = list(session.scalars(select(Action)).all())
    return {
        "events": session.query(OperationalEvent).count(),
        "incidents": session.query(Incident).count(),
        "actions": len(actions),
        "audit_logs": session.query(AuditLog).count(),
        "normal_events": skipped_counts.get("normal", 0),
        "warning_incidents": skipped_counts.get("warning_no_action", 0),
        "suppressions": skipped_counts.get("cooldown", 0),
        "action_succeeded": sum(1 for action in actions if action.state == ActionState.SUCCEEDED.value),
        "action_failed": sum(1 for action in actions if action.state == ActionState.FAILED.value),
        "retries": sum(max(action.attempts - 1, 0) for action in actions),
    }
