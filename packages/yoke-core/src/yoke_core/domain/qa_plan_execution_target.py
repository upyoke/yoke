"""Subject validation and target construction for ordered QA execution."""

from __future__ import annotations

from typing import Optional

from yoke_contracts.api.function_call import TargetRef
from yoke_core.domain.qa_plan_execution_result_state import QaPlanExecutionError


def build_plan_execution_target(
    *,
    public_ref: Optional[str],
    transition_id: Optional[str],
    deployment_run_id: Optional[str],
    deployment_stage: Optional[str],
    deployment_member: Optional[str],
    plan: Optional[str],
    project: Optional[str],
    requirement_id: Optional[int] = None,
) -> tuple[TargetRef, dict[str, str]]:
    """Validate one execution subject and build its function-call target."""
    if not public_ref and not deployment_run_id:
        if (
            not plan
            or not project
            or transition_id
            or deployment_stage
            or deployment_member
        ):
            raise QaPlanExecutionError(
                "standalone_subject_invalid: use --plan PLAN --project P without item, transition, stage or member"
            )
        return TargetRef(kind="global", project_id=project), {"plan": plan}
    if public_ref and deployment_run_id:
        raise QaPlanExecutionError(
            "exactly one of public_ref or deployment_run_id is required"
        )
    if public_ref:
        if bool(transition_id) == bool(deployment_stage) or deployment_member:
            raise QaPlanExecutionError(
                "item QA requires one transition or deployment stage, without a member selector"
            )
        if plan and not deployment_stage:
            raise QaPlanExecutionError(
                "item QA plan execution uses attached plans, not plan"
            )
        return (
            TargetRef(
                kind="item",
                public_ref=str(public_ref),
                project_id=project,
            ),
            {"deployment_stage": deployment_stage, **({"plan": plan} if plan else {})}
            if deployment_stage
            else {"transition_id": transition_id},
        )
    if transition_id:
        raise QaPlanExecutionError(
            "deployment-run QA plan execution has no workflow transition"
        )
    if deployment_member and not deployment_stage:
        raise QaPlanExecutionError("deployment member requires deployment stage")
    if not deployment_stage and not plan and requirement_id is None:
        raise QaPlanExecutionError("deployment-run QA plan execution requires plan")
    return (
        TargetRef(
            kind="deployment_run",
            deployment_run_id=str(deployment_run_id),
            project_id=project,
        ),
        {
            **({"plan": plan} if plan else {}),
            **({"deployment_stage": deployment_stage} if deployment_stage else {}),
            **({"deployment_member": deployment_member} if deployment_member else {}),
        },
    )


__all__ = ["build_plan_execution_target"]
