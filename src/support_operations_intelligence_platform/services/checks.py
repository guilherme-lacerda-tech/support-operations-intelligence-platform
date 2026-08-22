from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from support_operations_intelligence_platform.models import AuditLog, CheckRun, CheckState


class InvalidCheckTransition(ValueError):
    pass


ALLOWED_TRANSITIONS = {
    CheckState.PENDING.value: {
        CheckState.STARTED.value,
        CheckState.CANCELLED.value,
        CheckState.FAILED.value,
    },
    CheckState.STARTED.value: {
        CheckState.WAITING_CONFIRMATION.value,
        CheckState.CANCELLED.value,
        CheckState.FAILED.value,
    },
    CheckState.WAITING_CONFIRMATION.value: {
        CheckState.CONFIRMED.value,
        CheckState.TIMEOUT.value,
        CheckState.CANCELLED.value,
        CheckState.FAILED.value,
    },
    CheckState.CONFIRMED.value: set(),
    CheckState.TIMEOUT.value: set(),
    CheckState.CANCELLED.value: set(),
    CheckState.FAILED.value: set(),
}


def create_check(
    session: Session,
    *,
    name: str,
    asset_external_id: str,
    detail: str = "",
    now: datetime | None = None,
) -> CheckRun:
    now = now or datetime.now(UTC)
    check = CheckRun(
        name=name,
        asset_external_id=asset_external_id,
        state=CheckState.PENDING.value,
        detail=detail,
        created_at=now,
        updated_at=now,
    )
    session.add(check)
    session.flush()
    _audit(session, check, "check_created", f"Check {name} created")
    return check


def transition_check(
    session: Session,
    check: CheckRun,
    target_state: str,
    *,
    detail: str = "",
    timeout_seconds: int | None = None,
    now: datetime | None = None,
) -> CheckRun:
    now = now or datetime.now(UTC)
    target = target_state.lower()
    if target not in ALLOWED_TRANSITIONS.get(check.state, set()):
        raise InvalidCheckTransition(f"cannot transition check from {check.state} to {target}")

    check.state = target
    check.detail = detail or check.detail
    check.updated_at = now
    if target == CheckState.WAITING_CONFIRMATION.value and timeout_seconds is not None:
        check.confirmation_due_at = now + timedelta(seconds=timeout_seconds)
    if target in {
        CheckState.CONFIRMED.value,
        CheckState.TIMEOUT.value,
        CheckState.CANCELLED.value,
        CheckState.FAILED.value,
    }:
        check.confirmation_due_at = None

    session.flush()
    _audit(session, check, "check_transitioned", f"Check moved to {target}")
    return check


def expire_waiting_checks(session: Session, *, now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    checks = session.scalars(
        select(CheckRun)
        .where(CheckRun.state == CheckState.WAITING_CONFIRMATION.value)
        .where(CheckRun.confirmation_due_at.is_not(None))
        .where(CheckRun.confirmation_due_at <= now)
    ).all()
    for check in checks:
        transition_check(session, check, CheckState.TIMEOUT.value, detail="confirmation timeout", now=now)
    return len(checks)


def _audit(session: Session, check: CheckRun, event_type: str, message: str) -> None:
    session.add(
        AuditLog(
            event_type=event_type,
            entity_type="check",
            entity_id=check.id,
            message=message,
        )
    )
