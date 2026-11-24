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
