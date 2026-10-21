"""Which stage-wide requirements other sessions' live executions hold.

A stage-wide roster (a deployment stage without a member) splits into machine
groups, and each session walks its own live execution over disjoint groups.
A requirement frozen into another session's live roster is held: a begin
skips its group and waits when no ordered case can start. An
abandoned holder holds nothing; begin aborts it under the run lock before it
freezes a roster over the same requirements.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.qa_plan_execution_schema import (
    LIVE_PLAN_EXECUTION_SQL,
    LIVE_PLAN_EXECUTION_STATES,
)
from yoke_core.domain.qa_plan_execution_store import (
    QaPlanExecutionStateError,
    lock_plan_execution,
    select_plan_execution,
)


class StageRosterHeld(QaPlanExecutionStateError):
    """Another live roster holds cases that must settle before more work starts."""

    def __init__(self, execution: dict[str, Any]) -> None:
        self.execution = execution
        super().__init__(
            f"stage_roster_held: live QA plan execution {execution['id']} of "
            f"session {execution['session_id']} holds cases this "
            "stage must settle before more work can start. Keep the work claim, park, and rerun the "
            "same scoped QA command after that execution settles."
        )


def live_stage_executions(
    conn: Any, *, deployment_run_id: str, deployment_stage: str
) -> list[dict[str, Any]]:
    """Every live stage-wide execution of one run stage, oldest first."""
    rows = query_rows(
        conn,
        "SELECT id FROM qa_plan_executions WHERE deployment_run_id=%s "
        "AND deployment_stage=%s AND deployment_member_item_id IS NULL "
        f"AND state IN ({LIVE_PLAN_EXECUTION_SQL}) ORDER BY execution_order",
        (str(deployment_run_id), str(deployment_stage)),
    )
    return [select_plan_execution(conn, str(row["id"]), lock=False) for row in rows]


def held_requirements(
    conn: Any, *, deployment_run_id: str, deployment_stage: str, session_id: str
) -> dict[int, dict[str, Any]]:
    """Map each requirement another session's unabandoned execution holds."""
    from yoke_core.domain.qa_plan_execution_authority import (
        plan_execution_is_abandoned,
    )

    return {
        int(case["requirement_id"]): execution
        for execution in live_stage_executions(
            conn,
            deployment_run_id=deployment_run_id,
            deployment_stage=deployment_stage,
        )
        if str(execution["session_id"]) != str(session_id)
        and not plan_execution_is_abandoned(conn, execution)
        for case in execution["roster"]
    }


def admit_stage_roster(
    conn: Any,
    roster: list[dict[str, Any]],
    *,
    deployment_run_id: str,
    deployment_stage: str,
    session_id: str,
) -> bool:
    """Check custody under the run lock before freezing ``roster``.

    Refuse an overlapping live holder; abort abandoned holders. Each abort
    commits, so report whether any ran for the caller to read again.
    """
    from yoke_core.domain.qa_plan_execution_authority import (
        plan_execution_is_abandoned,
    )
    from yoke_core.domain.qa_plan_execution_lifecycle import (
        STALE_PLAN_EXECUTION_REASON,
        finish_plan_execution,
    )

    wanted = {int(row["requirement_id"]) for row in roster}
    aborted = False
    for execution in live_stage_executions(
        conn, deployment_run_id=deployment_run_id, deployment_stage=deployment_stage
    ):
        if str(execution["session_id"]) == str(session_id) or not wanted & {
            int(case["requirement_id"]) for case in execution["roster"]
        }:
            continue
        locked = lock_plan_execution(conn, str(execution["id"]))
        if locked["state"] not in LIVE_PLAN_EXECUTION_STATES:
            continue
        if not plan_execution_is_abandoned(conn, locked):
            raise StageRosterHeld(locked)
        finish_plan_execution(
            conn, locked, state="aborted", reason=STALE_PLAN_EXECUTION_REASON
        )
        aborted = True
    return aborted


__all__ = [
    "StageRosterHeld",
    "admit_stage_roster",
    "held_requirements",
    "live_stage_executions",
]
