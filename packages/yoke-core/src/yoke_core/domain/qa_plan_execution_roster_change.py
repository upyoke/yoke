"""A live execution whose requirements changed under it.

An execution freezes its roster when it begins. Superseding, adding or
retiring a requirement afterwards changes the roster ``begin`` would build
now. An execution that has not run a case yet holds nothing worth keeping, so
``begin`` retires it and starts over on the current roster. One that already
ran cases holds results the operator must decide about. A walk finishes on
its frozen roster. Other executions get the exact abort command. The check-in
refuses a cursor case that no longer owes an attempt, so a superseded case never runs.
"""

from __future__ import annotations

from typing import Any, NoReturn

from yoke_core.domain.qa_plan_execution_store import (
    QaPlanExecutionStateError,
    marker,
    result_rows,
)

ROSTER_CHANGED_REASON = "qa-roster-changed-before-start"


def abort_command(conn: Any, execution: dict[str, Any]) -> str:
    """The exact operator command that aborts ``execution``."""
    return f"yoke qa plan abort --execution-id {execution['id']} --reason TEXT"


def refuse_changed_roster(conn: Any, execution: dict[str, Any], *, message: str) -> NoReturn:
    """Preserve a walk for hand-back and review when begin sees a new roster."""
    conn.rollback()
    execution_id = execution["id"]
    if execution["state"] in {"walking", "awaiting_walk_review"}:
        raise QaPlanExecutionStateError(
            f"qa_walk_in_progress: execution {execution_id} has a frozen walk "
            "on a different roster. Finish the dispatched `yoke qa mission walk-end` "
            "for any outstanding host cleanup, then use "
            f"`yoke qa plan review-begin --execution-id {execution_id}` and "
            "`yoke qa plan review-submit` to record the verdicts."
        )
    raise QaPlanExecutionStateError(
        f"qa_roster_changed: {message} Abort it with `{abort_command(conn, execution)}`, "
        "then run the plan again to start on the current requirements."
    )


def retire_unstarted_changed_roster(
    conn: Any, execution: dict[str, Any], *, digest: str
) -> bool:
    """Return whether ``execution`` was retired because its roster changed.

    Unchanged rosters return ``False`` so the caller resumes. A changed roster
    with no case run is aborted, like an abandoned one, and the caller builds
    and inserts the replacement. A changed roster with cases already run
    refuses with the recovery appropriate to the execution's state.
    """
    if str(execution["roster_digest"]) == digest:
        return False
    execution_id = str(execution["id"])
    if int(execution["cursor_ordinal"]) > 0 or result_rows(conn, execution_id):
        refuse_changed_roster(
            conn,
            execution,
            message=(
                f"QA requirements changed after execution {execution_id} already ran cases, "
                "so it cannot resume on its frozen roster."
            ),
        )
    from yoke_core.domain.qa_plan_execution_lifecycle import finish_plan_execution

    finish_plan_execution(
        conn,
        execution,
        state="aborted",
        reason=ROSTER_CHANGED_REASON,
    )
    return True


def require_cursor_case_current(conn: Any, execution: dict[str, Any]) -> None:
    """Refuse a check-in whose next case no longer owes an attempt.

    Uses the same predicate that builds rosters, so a case superseded, replaced
    or discharged after the roster froze is refused before it runs.
    """
    from yoke_core.domain.qa_obligation_settlement import unanswered_attempt_sql
    from yoke_core.domain.qa_plan_execution_abort_state import abort_request

    roster = execution.get("roster") or []
    cursor = int(execution["cursor_ordinal"])
    if execution["state"] != "active" or cursor >= len(roster):
        return
    if abort_request(execution) is not None:
        return  # The check-in reports the abort; its retracted case cannot run.
    requirement_id = int(roster[cursor]["requirement_id"])
    row = conn.execute(
        f"SELECT 1 FROM qa_requirements WHERE id={marker(conn)} "
        f"AND NOT ({unanswered_attempt_sql(conn)})",
        (requirement_id,),
    ).fetchone()
    if row is None:
        return
    conn.rollback()
    raise QaPlanExecutionStateError(
        f"qa_case_superseded: requirement {requirement_id} at roster position "
        f"{cursor} of execution {execution['id']} was superseded or replaced "
        "after the roster froze, so it will not run. Abort the execution with "
        f"`{abort_command(conn, execution)}`, then run the plan again to start "
        "on the current requirements."
    )


def checkin(conn: Any, execution: dict[str, Any]) -> None:
    """Renew a client's liveness unless its next case was superseded."""
    from yoke_core.domain.qa_plan_execution_state import heartbeat_plan_execution

    require_cursor_case_current(conn, execution)
    heartbeat_plan_execution(conn, execution)
