"""Read and enforce custody of the cases frozen into live QA rosters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.qa_plan_execution_schema import (
    LIVE_PLAN_EXECUTION_SQL,
    LIVE_PLAN_EXECUTION_STATES,
)
from yoke_core.domain.qa_plan_execution_store import (
    QaPlanExecutionStateError,
    lock_plan_execution,
    marker,
    select_plan_execution,
)


@dataclass(frozen=True)
class PartitionScope:
    item_id: int | None = None
    transition_id: str | None = None
    deployment_run_id: str | None = None
    deployment_stage: str | None = None
    deployment_member_item_id: int | None = None
    standalone_plan_id: int | None = None

    @property
    def stage_wide(self) -> bool:
        return bool(self.deployment_stage and self.deployment_member_item_id is None)

    def predicate(self, bind: str) -> tuple[str, tuple]:
        if self.standalone_plan_id is not None:
            return f"standalone_plan_id={bind}", (self.standalone_plan_id,)
        if self.item_id is not None:
            return (
                f"item_id={bind} AND transition_id={bind}",
                (self.item_id, self.transition_id),
            )
        if self.deployment_run_id is None:
            raise QaPlanExecutionStateError("QA partition custody needs a subject")
        return (
            f"deployment_run_id={bind} AND COALESCE(deployment_stage,'')={bind} "
            f"AND COALESCE(deployment_member_item_id,0)={bind}",
            (
                self.deployment_run_id,
                self.deployment_stage or "",
                self.deployment_member_item_id or 0,
            ),
        )


class PartitionUnavailable(QaPlanExecutionStateError):
    code = "qa_partition_unavailable"


def live_partition_executions(conn: Any, scope: PartitionScope) -> list[dict[str, Any]]:
    if scope.stage_wide:
        from yoke_core.domain.qa_stage_execution_holders import live_stage_executions

        return live_stage_executions(
            conn,
            deployment_run_id=str(scope.deployment_run_id),
            deployment_stage=scope.deployment_stage,
        )
    predicate, params = scope.predicate(marker(conn))
    rows = query_rows(
        conn,
        f"SELECT id FROM qa_plan_executions WHERE {predicate} "
        f"AND state IN ({LIVE_PLAN_EXECUTION_SQL}) ORDER BY execution_order",
        params,
    )
    return [select_plan_execution(conn, str(row["id"]), lock=False) for row in rows]


def case_identity(row: dict[str, Any], scope: PartitionScope) -> int | tuple:
    if scope.standalone_plan_id is not None:
        return row["case_key"], row["baseline_position"]
    return int(row["requirement_id"])


def partition_unavailable(key: str, reason: str) -> PartitionUnavailable:
    return PartitionUnavailable(
        f"qa_partition_unavailable: partition {key} {reason}. "
        "Read the current partitions with `yoke qa plan partitions` using the "
        "same subject flags, then run a free partition by its key."
    )


def held_partition_cases(
    conn: Any, scope: PartitionScope
) -> dict[int | tuple, dict[str, Any]]:
    """Report live custody without changing execution or host state."""
    from yoke_core.domain.qa_plan_execution_authority import plan_execution_is_abandoned

    return {
        case_identity(row, scope): execution
        for execution in live_partition_executions(conn, scope)
        if not plan_execution_is_abandoned(conn, execution)
        for row in execution["roster"]
    }


def admit_partition(
    conn: Any,
    scope: PartitionScope,
    *,
    key: str,
    roster: list[dict[str, Any]],
    session_id: str,
) -> bool:
    """Under the subject lock, refuse held cases and clean up abandoned custody."""
    from yoke_core.domain.qa_plan_execution_authority import plan_execution_is_abandoned
    from yoke_core.domain.qa_plan_execution_lifecycle import (
        STALE_PLAN_EXECUTION_REASON,
        finish_plan_execution,
    )

    wanted = {case_identity(row, scope) for row in roster}
    aborted = False
    for execution in live_partition_executions(conn, scope):
        if str(execution["session_id"]) == session_id or wanted.isdisjoint(
            case_identity(row, scope) for row in execution["roster"]
        ):
            continue
        locked = lock_plan_execution(conn, str(execution["id"]))
        if locked["state"] not in LIVE_PLAN_EXECUTION_STATES or wanted.isdisjoint(
            case_identity(row, scope) for row in locked["roster"]
        ):
            continue
        if not plan_execution_is_abandoned(conn, locked):
            if scope.stage_wide:
                from yoke_core.domain.qa_stage_execution_holders import StageRosterHeld

                raise StageRosterHeld(locked, key)
            raise partition_unavailable(
                key, f"is held by execution {locked['id']} in session {locked['session_id']}"
            )
        finish_plan_execution(
            conn, locked, state="aborted", reason=STALE_PLAN_EXECUTION_REASON, commit=False
        )
        aborted = True
    return aborted
