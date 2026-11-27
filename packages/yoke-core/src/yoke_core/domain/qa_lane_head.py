"""Reconcile the exact server-selected QA lane before the first run write."""

from __future__ import annotations

from yoke_contracts.api.function_call import ActorContext, TargetRef

from yoke_core.domain import qa_case_execution as cases
from yoke_core.domain.lane_head_record import reconcile_lane_head


def reconcile_case_lane(case: dict, actor: ActorContext | None) -> str:
    if (
        not case.get("lane_path")
        or not case.get("lane_id")
        or case.get("lane_state", "active") != "active"
    ):
        return ""
    head, error = reconcile_lane_head(
        str(case.get("project") or ""),
        {
            "path": case["lane_path"],
            "branch": case.get("lane_branch"),
            "commit_sha": case.get("lane_commit_sha"),
        },
        session_id=actor.session_id if actor else None,
    )
    if error:
        raise cases.QaCaseExecutionError(error)
    return head


def reconcile_plan_lanes(
    target: TargetRef,
    *,
    transition_id: str,
    requirement_id: int | None,
    checkout_path: str | None,
    expected_branch: str | None,
    actor: ActorContext,
    call,
) -> None:
    """Resolve the lane with the same case selector the plan roster uses."""
    selectors = dict(actor=actor, checkout_path=checkout_path, expected_branch=expected_branch)
    if requirement_id is not None:
        reconcile_case_lane(cases.fetch_case_execution_context(requirement_id, **selectors), actor)
        return
    result = call(function_id="qa.requirement.list", target=target, payload={}, actor=actor)
    candidates = (
        row for row in result.get("rows") or ()
        if row.get("workflow_transition_id") == transition_id
        and not row.get("waived_at")
        and row.get("qa_phase") != "post_deploy"
        and row.get("runner_id") in {"worktree_run", "ci_run"}
    )
    seen = set()
    for row in candidates:
        task = (row.get("epic_id"), row.get("task_num"))
        if task in seen:
            continue
        seen.add(task)
        case = cases.fetch_case_execution_context(int(row["id"]), **selectors)
        reconcile_case_lane(case, actor)


def reconcile_walk_lane(target: TargetRef, result: dict, actor: ActorContext) -> bool:
    """Record the claimant lane's HEAD before a free walk partition's grant leaves it.

    A delegated walker begins against the branch and commit this read issues,
    so an unrecorded lane HEAD would refuse its first begin as ``qa_lane_moved``.
    Returns whether a new HEAD was recorded, so the caller rereads the binding.
    """
    from yoke_core.domain.lane_head_client import LaneHeadClientError, read_item_lanes

    lane_id = (result.get("lane") or {}).get("lane_id")
    if lane_id is None or not any(
        row.get("kind") == "walk" and row.get("state") == "free"
        for row in result.get("partitions") or ()
    ):
        return False
    project, lanes = read_item_lanes(
        TargetRef(kind="item", public_ref=target.public_ref, project_id=target.project_id),
        actor=actor,
    )
    record = next((row for row in lanes if row.get("id") == lane_id), None)
    if record is None:
        return False
    head, error = reconcile_lane_head(project, record, session_id=actor.session_id)
    if error:
        raise LaneHeadClientError(error)
    return bool(head)
