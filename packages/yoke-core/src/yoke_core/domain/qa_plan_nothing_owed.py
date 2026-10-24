"""Refuse a deployment plan run that owes no case, naming what still blocks.

A plan run used to replay the whole roster when every case had already
passed on its target, because stage acceptance wanted a completed scoped
execution. Acceptance now anchors on the newest stopped execution when every
case passed, so once any scoped execution on the target recorded the passes
a replay proves nothing new and cannot clear a pending review.
``yoke qa plan run`` refuses instead, and lists the stage's real blockers
with the next command each one names. Passes recorded outside every plan
execution still owe the one walk acceptance settles on.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from yoke_contracts.refusal_recovery import compose_refusal

from yoke_core.domain.qa_pending_agent_review import PendingAgentReview
from yoke_core.domain.qa_plan_execution_store import QaPlanExecutionStateError

NOTHING_OWED_CODE = "qa_plan_nothing_owed"


class QaPlanNothingOwed(QaPlanExecutionStateError):
    """Every roster case passed on this target or waits on a pending review."""


def scoped_execution_recorded(
    conn: Any,
    roster: list[dict[str, Any]],
    *,
    deployment_run_id: str | None,
    deployment_stage: str | None,
    deployment_member_item_id: int | None,
) -> bool:
    """Whether a settled execution on this roster's target already exists.

    Passes recorded outside any plan execution leave the stage without the
    scoped execution its acceptance settles on, so that one walk is still
    owed; once one exists, re-running the roster proves nothing new.
    """
    row = conn.execute(
        "SELECT 1 FROM qa_plan_executions WHERE deployment_run_id=%s "
        "AND deployment_stage=%s AND COALESCE(deployment_member_item_id,0)=%s "
        "AND execution_target_digest=%s "
        "AND state IN ('completed','aborted','error') LIMIT 1",
        (
            deployment_run_id,
            deployment_stage,
            deployment_member_item_id or 0,
            str(roster[0].get("execution_target_digest") or ""),
        ),
    ).fetchone()
    return row is not None


def _review_blockers(held: Mapping[int, PendingAgentReview]) -> list[str]:
    by_execution: dict[str, tuple[PendingAgentReview, list[int]]] = {}
    for requirement_id, pending in sorted(held.items()):
        by_execution.setdefault(pending.execution_id, (pending, []))[1].append(
            requirement_id
        )
    return [
        f"requirements {', '.join(f'#{rid}' for rid in ids)} await the review of "
        f"{pending.state} execution {pending.execution_id}: {pending.next_action()}"
        for pending, ids in by_execution.values()
    ]


def nothing_owed(
    conn: Any,
    *,
    roster_size: int,
    deployment_run_id: str | None,
    deployment_stage: str | None,
    held: Mapping[int, PendingAgentReview] | None = None,
) -> QaPlanNothingOwed:
    """The refusal for a roster with no case left to capture on its target."""
    blockers = _review_blockers(held or {})
    if deployment_run_id and deployment_stage:
        from yoke_core.domain.deployment_qa_stage_outstanding import (
            qa_stage_outstanding,
        )

        outstanding = qa_stage_outstanding(
            conn, run_id=str(deployment_run_id), stage_name=str(deployment_stage)
        )
        if outstanding is not None:
            blockers.extend(
                line for line in outstanding.lines if line not in blockers
            )
    scope = (
        f"deployment run {deployment_run_id} stage {deployment_stage!r}"
        if deployment_run_id
        else "this item transition"
    )
    evaluated = (
        f"{roster_size} roster case(s) for {scope}: each already passed on its "
        "execution target or waits on a pending review"
    )
    if not blockers:
        return QaPlanNothingOwed(
            compose_refusal(
                f"{NOTHING_OWED_CODE}: nothing owed; this plan run would replay "
                "a fully passed roster",
                evaluated=f"{evaluated}; the stage reports no QA blocker",
                recovery=(
                    "re-drive the deployment run so the stage settles from the "
                    f"recorded passes; read `yoke deployment-runs get "
                    f"{deployment_run_id}` for its current state"
                    if deployment_run_id
                    else "read the results with `yoke qa requirement list`"
                ),
            )
        )
    return QaPlanNothingOwed(
        compose_refusal(
            f"{NOTHING_OWED_CODE}: nothing owed; this plan run has no case "
            "left to capture and would only replay passed work",
            evaluated=f"{evaluated}. Stage blockers: " + " | ".join(blockers),
            recovery=(
                "run the next command each stage blocker names; a case with no "
                "verdict yet runs through the stage/member `yoke qa plan run` "
                "command, without a `--plan` selection that leaves it out"
            ),
        )
    )


__all__ = [
    "NOTHING_OWED_CODE",
    "QaPlanNothingOwed",
    "nothing_owed",
    "scoped_execution_recorded",
]
