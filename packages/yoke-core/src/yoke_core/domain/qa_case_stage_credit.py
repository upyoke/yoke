"""Direct item-case passes settle members; plan groups retain ordered walks."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Optional

from yoke_contracts.api.function_call import ActorContext
from yoke_contracts.qa_case_starting_state import is_host_command

from yoke_core.domain.machine_qa_case_machine import (
    MachineConstraintError,
    refuse_stored_host_names,
)


def item_scoped_stage_plan_run_command(case: Mapping[str, Any]) -> str | None:
    """The ordered plan-group command, when this case belongs to a group.

    Direct member cases settle from their own current passes.
    """
    run_id = str(case.get("deployment_run_id") or "").strip()
    stage = str(case.get("deployment_stage") or "").strip()
    shared = ((case.get("execution_target") or {}).get("deployment") or {}).get(
        "shared_plan"
    )
    if not run_id or not stage or not shared:
        return None
    return (
        f"yoke qa plan run --deployment-run-id {run_id} --stage {stage} "
        f"--plan {shared['plan_id']}"
    )


def item_scoped_stage_credit_refusal(case: Mapping[str, Any]) -> str | None:
    """Return a refusal when a case run would credit nothing toward its stage."""
    command = item_scoped_stage_plan_run_command(case)
    if command is None:
        return None
    stage = str(case["deployment_stage"]).strip()
    run_id = str(case["deployment_run_id"]).strip()
    shared = ((case.get("execution_target") or {}).get("deployment") or {}).get(
        "shared_plan"
    )
    if shared:
        return (
            f"STAGE CREDIT REFUSAL: this case belongs to the plan group of plan "
            f"{shared['plan_id']} on {run_id} stage {stage!r}. A direct case pass "
            "does not complete the group's ordered execution. Run the group "
            f"instead:\n  {command}"
        )
    return None



def execute_authorized_case(
    requirement_id: int,
    *,
    base_url: str = "",
    test_machine: str | None = None,
    expected_branch: Optional[str] = None,
    expected_sha: Optional[str] = None,
    timeout_seconds: Optional[int] = None,
    checkout_path: Optional[str | Path] = None,
    allow_tree_mismatch: bool = False,
    actor: Optional[ActorContext] = None,
) -> dict:
    """Authorize a case, preserving a plan group's ordered execution."""
    from yoke_core.domain import qa_case_execution as cases

    selection = {}
    if checkout_path is not None:
        selection["checkout_path"] = checkout_path
    if expected_branch:
        selection["expected_branch"] = expected_branch
    case = cases.fetch_case_execution_context(requirement_id, actor=actor, **selection)
    refusal = item_scoped_stage_credit_refusal(case)
    if refusal:
        raise cases.QaCaseExecutionError(refusal)
    try:
        refuse_stored_host_names(case)
    except MachineConstraintError as exc:
        raise cases.QaCaseExecutionError(str(exc)) from exc
    from yoke_core.domain.qa_lane_head import reconcile_case_lane

    if reconcile_case_lane(case, actor):
        case = cases.fetch_case_execution_context(requirement_id, actor=actor, **selection)
    runner_options = {
        "base_url": base_url,
        "expected_branch": expected_branch,
        "expected_sha": expected_sha,
        "timeout_seconds": timeout_seconds,
        "checkout_path": checkout_path,
        "allow_tree_mismatch": allow_tree_mismatch,
        "actor": actor,
    }
    if test_machine is not None:
        runner_options["test_machine"] = test_machine
    if is_host_command(case):
        from yoke_core.domain.qa_case_mission_execution import execute_single_plan_case

        return execute_single_plan_case(case, kind="host_command", **runner_options)
    return cases.execute_case_context(case, **runner_options)


__all__ = [
    "execute_authorized_case",
    "item_scoped_stage_credit_refusal",
    "item_scoped_stage_plan_run_command",
]
