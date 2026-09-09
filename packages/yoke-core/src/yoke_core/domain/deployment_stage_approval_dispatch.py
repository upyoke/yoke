"""Pipeline-side adapter for one deployment run human approval stage.

The deploy driver runs wherever an operator started it; the control plane
it reads runs whatever revision was last deployed to it. Those are routinely
different builds, so the approval verdict is derived on the serving side and
this module only carries the answer back to the step runner.
"""

from __future__ import annotations

from yoke_core.domain.deployment_approval_requests import (
    EVALUATE_STAGE_APPROVAL_FUNCTION,
)


def dispatch_deployment_stage_approval(
    run_id: str,
    stage_name: str,
) -> tuple[int, str]:
    """Deployment step-runner adapter for one human approval stage.

    The verdict is derived on the build that SERVES this control plane, not
    in the driver. A release driver runs the candidate revision while the
    control plane still runs the deployed one, so evaluating here would read
    the candidate's columns out of the deployed build's database — and a
    release that adds or removes a column crashes its own approval gate.
    """
    from yoke_contracts.api.function_call import TargetRef
    from yoke_core.domain.control_plane_transport import serving_authority

    try:
        result = serving_authority(
            EVALUATE_STAGE_APPROVAL_FUNCTION,
            {"stage": stage_name},
            TargetRef(kind="workflow_run", workflow_run_id=run_id),
        )
    except RuntimeError as exc:
        return 1, (
            f"deployment stage {stage_name!r} approval could not be "
            f"evaluated on the serving control plane: {exc}"
        )
    if result.get("satisfied"):
        return 0, ""
    if result.get("resolution_action") == "reject":
        return 1, (
            f"deployment stage {stage_name!r} was rejected through "
            f"decision request {result.get('request_id')}"
        )
    print(
        f"Awaiting Inbox decision {result.get('request_id')} for stage '{stage_name}'"
    )
    return -2, ""


__all__ = ["dispatch_deployment_stage_approval"]
