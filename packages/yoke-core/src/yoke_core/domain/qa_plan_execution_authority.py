"""Subject, ownership, and abandonment authority for QA plan executions."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from yoke_core.domain import db_backend


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


def owning_session_is_parked(conn: Any, execution: Mapping[str, Any]) -> bool:
    """Report whether a live owning session has declared a deliberate wait.

    A parked session is present and waiting on purpose -- an operator told
    its walker to hold. The park is only ever an answer for a session that
    is still there, so a session that has ended stops shielding whatever it
    owned no matter what mode its last row recorded.
    """
    from yoke_core.domain.schema_common import _table_exists
    from yoke_core.domain.session_mode import session_is_parked

    session_id = str(execution.get("session_id") or "")
    if not session_id or not _table_exists(conn, "harness_sessions"):
        return False
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        "SELECT mode FROM harness_sessions "
        f"WHERE session_id={marker} AND ended_at IS NULL",
        (session_id,),
    ).fetchone()
    if row is None:
        return False
    return session_is_parked(row["mode"] if hasattr(row, "keys") else row[0])


def plan_execution_is_abandoned(
    conn: Any,
    execution: Mapping[str, Any],
    *,
    now: datetime | None = None,
) -> bool:
    """Report whether a non-progressing execution has actually been left.

    Silence means two different things. An execution whose owner is gone has
    been abandoned and must be settled, or every decision it raised waits
    forever. An execution whose owner parked is silent because a person told
    it to hold, and settling that one destroys a walk that is still coming
    back. Only the first is abandoned.
    """
    if not plan_execution_is_stale(execution, now=now):
        return False
    return not owning_session_is_parked(conn, execution)


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
    conn: Any,
    execution: Mapping[str, Any],
    *,
    item_id: int | None = None,
    deployment_run_id: str | None = None,
    actor_id: str | None,
    session_id: str,
    now: datetime | None = None,
) -> None:
    """Let any caller on the subject abandon an execution nobody is holding.

    Running an execution stays bound to the session that owns it. Abandoning
    one is the opposite need: the session that owned a stranded execution is
    by definition the session that is no longer there, so requiring it leaves
    the row unsettleable by every registered surface. An execution that is
    still reporting progress -- or whose owner parked it on instruction --
    keeps its owner-only guard.
    """
    from yoke_core.domain.qa_plan_execution_store import same_owner

    require_plan_execution_subject(
        execution,
        item_id=item_id,
        deployment_run_id=deployment_run_id,
    )
    if same_owner(execution, actor_id=actor_id, session_id=session_id):
        return
    if owning_session_is_parked(conn, execution):
        _fail(
            "QA plan execution belongs to session "
            f"{str(execution.get('session_id') or '')!r}, which is parked and "
            "still holding this walk; abandoning it is not open to another "
            "session. Ask that session to unpark and finish or abort its own "
            "execution, or end it, then retry"
        )
    if not plan_execution_is_stale(execution, now=now):
        _fail(
            "QA plan execution is still reporting progress and belongs to a "
            "different actor or session; abandoning it is only open to another "
            "session once it has stopped heartbeating for "
            f"{PLAN_EXECUTION_STALE_SECONDS // 60} minutes"
        )


__all__ = [
    "PLAN_EXECUTION_STALE_SECONDS",
    "owning_session_is_parked",
    "plan_execution_is_abandoned",
    "plan_execution_is_stale",
    "require_plan_execution_abandon_authority",
    "require_plan_execution_owner",
    "require_plan_execution_subject",
]
