"""Run exactly one mission through the existing ordered execution lifecycle."""

from yoke_core.domain.qa_case_execution import QaCaseExecutionError
from yoke_core.domain.qa_plan_execution import QaPlanExecutionError, execute_plan


def execute_mission_case(case: dict, **kwargs) -> dict:
    """Select the case's durable subject without materializing sibling cases."""
    requirement_id = int(case["requirement_id"])
    if case.get("starting_state") == "inherit":
        raise QaCaseExecutionError(
            "qa_single_mission_inherits: this mission requires its predecessor in the same execution; "
            "run its attached plan with `yoke qa plan run --help` for the subject flags"
        )
    if case.get("standalone_execution_id"):
        raise QaCaseExecutionError(
            "qa_single_mission_standalone: this case already belongs to a standalone execution; "
            f"resume it with `yoke qa plan run --plan {case['plan_id']} --project {case['project']} "
            f"--resume-execution-id {case['standalone_execution_id']}`"
        )
    subject = {"project": case["project"], "requirement_id": requirement_id}
    if case.get("deployment_run_id"):
        subject.update(
            deployment_run_id=case["deployment_run_id"],
            deployment_stage=case.get("deployment_stage"),
            deployment_member=case.get("deployment_member_ref"),
            plan=str(case["plan_id"]) if case.get("plan_id") else None,
        )
    else:
        subject.update(
            public_ref=case.get("public_ref"),
            transition_id=case.get("workflow_transition_id"),
        )
    try:
        return execute_plan(**subject, **kwargs)
    except QaPlanExecutionError as exc:
        raise QaCaseExecutionError(
            f"qa_single_mission_start_failed: {exc}. Preserve this receipt; "
            f"retry `yoke qa case run --requirement-id {requirement_id}` after the named recovery. "
            "If the server rejects requirement_id, update the serving Yoke release before retrying."
        ) from exc
