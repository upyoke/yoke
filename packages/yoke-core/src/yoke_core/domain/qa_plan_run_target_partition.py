"""Deployment-run plan runs skip cases that already passed on the same target.

An aborted scoped execution keeps the passes it recorded, but a fresh
execution used to roster every case again from cursor 0, so a rerun after an
abort replayed work the target had already proved. Run mode now leaves out
each requirement whose newest run passed, still proves the live method
config, and recorded the roster's own execution target digest. Any execution
may have recorded that pass, including an aborted one. A pass recorded
against another target (a new lineage or run) proves nothing here, and a
pass the stage still grades unresolved (no evidence) stays owed. A passed case
stays while a later case of its chain still owes a verdict, so the chain
still runs from its opener.

A live execution keeps its own immutable roster. When every case already
passed, nothing is owed: the run refuses with ``qa_plan_nothing_owed`` and
names the stage's real blockers instead of replaying the roster, because
stage acceptance anchors on the newest stopped execution once every case
passed.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.qa_latest_execution import latest_executions
from yoke_core.domain.qa_plan_case_chain import settled_chain_tails
from yoke_core.domain.qa_plan_execution_store import (
    live_plan_execution_id,
    select_plan_execution,
)
from yoke_core.domain.qa_requirement_pass_currency import (
    current_passing_requirements,
    recorded_execution_target_digest,
)


def target_passed_requirements(
    conn: Any,
    roster: list[dict[str, Any]],
    *,
    deployment_run_id: str | None,
    deployment_stage: str | None,
    deployment_member_item_id: int | None,
) -> set[int]:
    """Roster requirements passed on the row's target that acceptance accepts.

    A pass the stage still grades as unresolved, such as one without
    evidence, stays owed so the fresh execution captures it again.
    """
    digests = {
        int(row["requirement_id"]): str(row.get("execution_target_digest") or "")
        for row in roster
    }
    current = current_passing_requirements(conn, digests)
    latest = latest_executions(conn, current)
    passed = {
        requirement_id
        for requirement_id in current
        if requirement_id in latest
        and digests[requirement_id]
        and recorded_execution_target_digest(latest[requirement_id]["raw_result"])
        == digests[requirement_id]
    }
    if not passed or not deployment_run_id or not deployment_stage:
        return passed
    from yoke_core.domain.deployment_qa_stage_case_failures import case_failures

    deployment = (roster[0].get("execution_target") or {}).get("deployment") or {}
    failures = case_failures(
        conn,
        run_id=str(deployment_run_id),
        stage_name=deployment_stage,
        member_item_id=deployment_member_item_id,
        execution_target_digest=str(roster[0]["execution_target_digest"]),
        shared_plan_id=(deployment.get("shared_plan") or {}).get("plan_id"),
    )
    return passed - {failure.requirement_id for failure in failures}


def run_target_partition(
    conn: Any,
    roster: list[dict[str, Any]],
    *,
    deployment_run_id: str | None,
    deployment_stage: str | None,
    deployment_member_item_id: int | None,
    session_id: str | None = None,
) -> list[dict[str, Any]]:
    """The roster still owed on this target, renumbered from ordinal 0.

    ``session_id`` names whose live roster stays whole on a stage-wide subject.
    """
    scope = dict(
        deployment_run_id=deployment_run_id,
        deployment_stage=deployment_stage,
        deployment_member_item_id=deployment_member_item_id,
    )
    passed = target_passed_requirements(conn, roster, **scope)
    live_id = live_plan_execution_id(conn, **scope, session_id=session_id)
    if live_id is not None:
        live = select_plan_execution(conn, live_id, lock=False)
        passed -= {int(row["requirement_id"]) for row in live["roster"]}
    passed = settled_chain_tails(roster, passed)
    open_rows = [row for row in roster if int(row["requirement_id"]) not in passed]
    if not open_rows:
        from yoke_core.domain.qa_plan_nothing_owed import nothing_owed

        raise nothing_owed(
            conn,
            roster_size=len(roster),
            deployment_run_id=deployment_run_id,
            deployment_stage=deployment_stage,
        )
    if len(open_rows) == len(roster):
        return roster
    return [{**row, "ordinal": index} for index, row in enumerate(open_rows)]


__all__ = ["run_target_partition", "target_passed_requirements"]
