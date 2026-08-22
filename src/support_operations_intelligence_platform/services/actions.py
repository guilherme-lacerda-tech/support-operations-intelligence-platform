from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from time import sleep
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from support_operations_intelligence_platform.models import Action, ActionState, AuditLog


class ActionTimeoutError(RuntimeError):
    pass


@dataclass(frozen=True)
class ActionAttemptResult:
    succeeded: bool
    detail: str


SyntheticTransport = Callable[[Action, float], ActionAttemptResult]


def default_transport(action: Action, timeout_seconds: float) -> ActionAttemptResult:
    if timeout_seconds <= 0:
        raise ActionTimeoutError("timeout must be positive")
    sleep(min(timeout_seconds, 0.01))
    if "permanent_failure" in action.detail:
        return ActionAttemptResult(False, "synthetic permanent failure")
    if ("fail_once" in action.detail or "transient_then_success" in action.detail) and action.attempts <= 1:
        return ActionAttemptResult(False, "synthetic transient failure")
    return ActionAttemptResult(True, f"synthetic {action.action_type} completed")


def execute_action_with_retry(
    session: Session,
    action: Action,
    *,
    max_attempts: int = 3,
    timeout_seconds: float = 0.2,
    transport: SyntheticTransport = default_transport,
) -> Action:
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")

    while action.state not in {ActionState.SUCCEEDED.value, ActionState.FAILED.value}:
        execute_action_once(
            session,
            action,
            max_attempts=max_attempts,
            timeout_seconds=timeout_seconds,
            retry_delay_seconds=0,
            transport=transport,
        )

    return action


def execute_action_once(
    session: Session,
    action: Action,
    *,
    max_attempts: int = 3,
    timeout_seconds: float = 0.2,
    retry_delay_seconds: float = 0,
    transport: SyntheticTransport = default_transport,
    now: datetime | None = None,
) -> Action:
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")
    if action.state in {ActionState.SUCCEEDED.value, ActionState.FAILED.value, ActionState.SKIPPED.value}:
        return action

    now = now or datetime.now(UTC)
    action.attempts += 1
    original_detail = action.detail
    try:
        result = transport(action, timeout_seconds)
    except TimeoutError as exc:
        outcome_detail = f"timeout: {exc}"
        succeeded = False
    except ActionTimeoutError as exc:
        outcome_detail = str(exc)
        succeeded = False
    else:
        outcome_detail = result.detail
        succeeded = result.succeeded

    if succeeded:
        action.state = ActionState.SUCCEEDED.value
        action.detail = outcome_detail
    elif "permanent_failure" in original_detail or action.attempts >= max_attempts:
        action.state = ActionState.FAILED.value
        action.detail = outcome_detail
    else:
        action.state = ActionState.RETRY.value
        action.next_attempt_at = now + timedelta(seconds=retry_delay_seconds)

    action.lease_id = None
    action.leased_at = None
    action.updated_at = now
    session.add(
        AuditLog(
            event_type="action_executed",
            entity_type="action",
            entity_id=action.id,
            message=f"{action.action_type} finished as {action.state} after {action.attempts} attempts",
        )
    )
    session.flush()
    return action


def process_due_actions(
    session: Session,
    *,
    limit: int = 100,
    max_attempts: int = 3,
    timeout_seconds: float = 0.2,
    retry_delay_seconds: float = 0,
    lease_seconds: int = 60,
    transport: SyntheticTransport = default_transport,
    now: datetime | None = None,
) -> dict[str, int]:
    now = now or datetime.now(UTC)
    stale_lease_before = now - timedelta(seconds=lease_seconds)
    due_actions = list(
        session.scalars(
            select(Action)
            .where(Action.state.in_([ActionState.QUEUED.value, ActionState.RETRY.value]))
            .where(or_(Action.next_attempt_at.is_(None), Action.next_attempt_at <= now))
            .where(or_(Action.lease_id.is_(None), Action.leased_at <= stale_lease_before))
            .order_by(Action.next_attempt_at.asc().nullsfirst(), Action.created_at.asc())
            .limit(limit)
        ).all()
    )

    lease_id = f"lease_{uuid4().hex}"
    succeeded = 0
    failed = 0
    retried = 0
    for action in due_actions:
        action.lease_id = lease_id
        action.leased_at = now
        session.flush()
        execute_action_once(
            session,
            action,
            max_attempts=max_attempts,
            timeout_seconds=timeout_seconds,
            retry_delay_seconds=retry_delay_seconds,
            transport=transport,
            now=now,
        )
        succeeded += action.state == ActionState.SUCCEEDED.value
        failed += action.state == ActionState.FAILED.value
        retried += action.state == ActionState.RETRY.value

    return {
        "processed": len(due_actions),
        "succeeded": succeeded,
        "failed": failed,
        "retried": retried,
    }


@dataclass(frozen=True)
class ActionWorker:
    session_factory: Callable[[], Session]
    max_attempts: int = 3
    timeout_seconds: float = 0.2
    retry_delay_seconds: float = 0
    lease_seconds: int = 60

    def run_once(self, *, limit: int = 100, now: datetime | None = None) -> dict[str, int]:
        session = self.session_factory()
        try:
            result = process_due_actions(
                session,
                limit=limit,
                max_attempts=self.max_attempts,
                timeout_seconds=self.timeout_seconds,
                retry_delay_seconds=self.retry_delay_seconds,
                lease_seconds=self.lease_seconds,
                now=now,
            )
            session.commit()
            return result
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
