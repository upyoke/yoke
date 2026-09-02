"""Subject, ownership, and abandonment authority for QA plan executions."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping


PLAN_EXECUTION_STALE_SECONDS = 30 * 60


def _fail(message: str) -> None:
    from yoke_core.domain.qa_plan_execution_store import QaPlanExecutionStateError

    raise QaPlanExecutionStateError(message)


def plan_execution_is_stale(
    execution: Mapping[str, Any],
    *,
    now: datetime | None = None,
) -> bool:
    """Report whether an execution has stopped reporting progress.

    An unparseable or missing heartbeat counts as stale: a row that cannot
    say when it last progressed cannot claim it still is.
    """
    observed = now or datetime.now(timezone.utc)
    try:
        parsed = datetime.fromisoformat(
            str(execution.get("heartbeat_at")).replace("Z", "+00:00")
        )
    except ValueError:
        return True
    elapsed = (observed - parsed.astimezone(timezone.utc)).total_seconds()
    return elapsed > PLAN_EXECUTION_STALE_SECONDS


def require_plan_execution_subject(
    execution: Mapping[str, Any],
    *,
    item_id: int | None = None,
    deployment_run_id: str | None = None,
) -> None:
    """Bind an execution mutation to exactly the subject the caller named."""
    if (item_id is None) == (deployment_run_id is None):
        _fail("exactly one QA plan execution subject is required")
    if item_id is not None and (
        execution.get("item_id") is None or int(execution["item_id"]) != int(item_id)
    ):
        _fail("QA plan execution belongs to a different item")
    if deployment_run_id is not None and str(
        execution.get("deployment_run_id") or ""
    ) != str(deployment_run_id):
        _fail("QA plan execution belongs to a different deployment run")


def require_plan_execution_owner(
    execution: Mapping[str, Any],
    *,
    item_id: int | None = None,
    deployment_run_id: str | None = None,
    actor_id: str | None,
    session_id: str,
) -> None:
    """Bind every execution mutation to its subject, actor, and session."""
    from yoke_core.domain.qa_plan_execution_store import same_owner

    require_plan_execution_subject(
        execution,
        item_id=item_id,
        deployment_run_id=deployment_run_id,
    )
    if not same_owner(execution, actor_id=actor_id, session_id=session_id):
        _fail("QA plan execution belongs to a different actor or session")


def require_plan_execution_abandon_authority(
    execution: Mapping[str, Any],
    *,
    item_id: int | None = None,
    deployment_run_id: str | None = None,
    actor_id: str | None,
    session_id: str,
    now: datetime | None = None,
) -> None:
    """Let any caller on the subject abandon a non-progressing execution.

    Running an execution stays bound to the session that owns it. Abandoning
    one is the opposite need: the session that owned a stranded execution is
    by definition the session that is no longer there, so requiring it leaves
    the row unsettleable by every registered surface. An execution that is
    still reporting progress keeps its owner-only guard.
    """
    from yoke_core.domain.qa_plan_execution_store import same_owner

    require_plan_execution_subject(
        execution,
        item_id=item_id,
        deployment_run_id=deployment_run_id,
    )
    if same_owner(execution, actor_id=actor_id, session_id=session_id):
        return
    if not plan_execution_is_stale(execution, now=now):
        _fail(
            "QA plan execution is still reporting progress and belongs to a "
            "different actor or session; abandoning it is only open to another "
            "session once it has stopped heartbeating for "
            f"{PLAN_EXECUTION_STALE_SECONDS // 60} minutes"
        )


__all__ = [
    "PLAN_EXECUTION_STALE_SECONDS",
    "plan_execution_is_stale",
    "require_plan_execution_abandon_authority",
    "require_plan_execution_owner",
    "require_plan_execution_subject",
]
