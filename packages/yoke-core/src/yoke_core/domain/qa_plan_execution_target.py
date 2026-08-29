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
    plan: Optional[str],
    project: Optional[str],
) -> tuple[TargetRef, dict[str, str]]:
    """Validate one execution subject and build its function-call target."""
    if bool(public_ref) == bool(deployment_run_id):
        raise QaPlanExecutionError(
            "exactly one of public_ref or deployment_run_id is required"
        )
    if public_ref:
        if not transition_id:
            raise QaPlanExecutionError("item QA plan execution requires transition_id")
        if plan:
            raise QaPlanExecutionError(
                "item QA plan execution uses attached plans, not plan"
            )
        return (
            TargetRef(
                kind="item",
                public_ref=str(public_ref),
                project_id=project,
            ),
            {"transition_id": transition_id},
        )
    if transition_id:
        raise QaPlanExecutionError(
            "deployment-run QA plan execution has no workflow transition"
        )
    if not plan:
        raise QaPlanExecutionError("deployment-run QA plan execution requires plan")
    return (
        TargetRef(
            kind="deployment_run",
            deployment_run_id=str(deployment_run_id),
            project_id=project,
        ),
        {},
    )


__all__ = ["build_plan_execution_target"]
