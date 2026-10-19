"""Deployment-run plan runs skip cases that already passed on the same target.

An aborted scoped execution keeps the passes it recorded, but a fresh
execution used to roster every case again from cursor 0, so a rerun after an
abort replayed work the target had already proved. Run mode now leaves out
each requirement whose newest run passed, still proves the live method
config, and recorded the roster's own execution target digest. Any execution
may have recorded that pass, including an aborted one. A pass recorded
against another target (a new lineage or run) proves nothing here.

A live execution keeps its own immutable roster. When every case already
passed, the roster stays whole: stage acceptance needs a completed scoped
execution, and an empty roster has no target to run against.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.qa_latest_execution import latest_executions
from yoke_core.domain.qa_plan_execution_store import (
    live_plan_execution_id,
    select_plan_execution,
)
from yoke_core.domain.qa_plan_item_target_partition import Settle
from yoke_core.domain.qa_requirement_pass_currency import (
    current_passing_requirements,
    recorded_execution_target_digest,
)


def target_passed_requirements(conn: Any, roster: list[dict[str, Any]]) -> set[int]:
    """Roster requirements whose current pass was recorded on the row's target."""
    digests = {
        int(row["requirement_id"]): str(row.get("execution_target_digest") or "")
        for row in roster
    }
    current = current_passing_requirements(conn, digests)
    latest = latest_executions(conn, current)
    return {
        requirement_id
        for requirement_id in current
        if requirement_id in latest
        and digests[requirement_id]
        and recorded_execution_target_digest(latest[requirement_id]["raw_result"])
        == digests[requirement_id]
    }


def run_target_partition(
    conn: Any,
    roster: list[dict[str, Any]],
    *,
    deployment_run_id: str,
    deployment_stage: str | None,
    deployment_member_item_id: int | None,
    settle: Settle,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Return (settled reprint, roster still owed on this target)."""
    passed = target_passed_requirements(conn, roster)
    live_id = live_plan_execution_id(
        conn,
        deployment_run_id=deployment_run_id,
        deployment_stage=deployment_stage,
        deployment_member_item_id=deployment_member_item_id,
    )
    if live_id is not None:
        live = select_plan_execution(conn, live_id, lock=False)
        passed -= {int(row["requirement_id"]) for row in live["roster"]}
    open_rows = [row for row in roster if int(row["requirement_id"]) not in passed]
    if len(open_rows) == len(roster) or not open_rows:
        return settle(roster)
    return settle([{**row, "ordinal": index} for index, row in enumerate(open_rows)])


__all__ = ["run_target_partition", "target_passed_requirements"]
