from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from time import sleep

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
    if ("transient_failure" in action.detail or "fail_once" in action.detail) and action.attempts <= 1:
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

    last_detail = ""
    for attempt in range(1, max_attempts + 1):
        action.attempts = attempt
        try:
            result = transport(action, timeout_seconds)
        except TimeoutError as exc:
            last_detail = f"timeout: {exc}"
        except ActionTimeoutError as exc:
            last_detail = str(exc)
        else:
            last_detail = result.detail
            if result.succeeded:
                action.state = ActionState.SUCCEEDED.value
                break
        action.state = ActionState.FAILED.value

    action.detail = last_detail
    action.updated_at = datetime.now(UTC)
    audit_type = "action_succeeded" if action.state == ActionState.SUCCEEDED.value else "action_failed_final"
    session.add(
        AuditLog(
            event_type=audit_type,
            entity_type="action",
            entity_id=action.id,
            message=f"{action.action_type} finished as {action.state} after {action.attempts} attempts",
        )
    )
    session.flush()
    return action
