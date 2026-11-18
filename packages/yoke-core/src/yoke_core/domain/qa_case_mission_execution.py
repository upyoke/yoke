"""Run one machine-backed Command or mission through ordered plan execution."""

from yoke_core.domain.qa_case_execution import QaCaseExecutionError
from yoke_core.domain.qa_plan_execution import QaPlanExecutionError, execute_plan
from yoke_core.domain.qa_plan_execution_schema import TERMINAL_PLAN_EXECUTION_STATES


def _standalone_refusal(case: dict, kind: str) -> str:
    """Name the command that resumes the standalone case's owning execution."""
    execution_id = case["standalone_execution_id"]
    state = case.get("standalone_execution_state")
    fresh = f"yoke qa plan run --plan {case['plan_id']} --project {case['project']}"
    resume = f"`{fresh} --resume-execution-id {execution_id}`"
    owner = f"qa_single_{kind}_standalone: this case belongs to standalone execution {execution_id}"
    if state in TERMINAL_PLAN_EXECUTION_STATES:
        return (
            f"{owner}, which ended as {state} and can no longer walk it; "
            f"start a fresh execution of its plan with `{fresh}`"
        )
    if state is None:
        # A serving release older than this client does not report the state.
        return (
            f"{owner}; resume it with {resume}, or when that refuses "
            f"qa_resume_terminal start a fresh execution with `{fresh}`"
        )
    return f"{owner}; resume it with {resume}"


def execute_mission_case(case: dict, **kwargs) -> dict:
    """Run a mission in its own one-case roster."""
    return execute_single_plan_case(case, kind="mission", **kwargs)


def execute_single_plan_case(case: dict, *, kind: str, **kwargs) -> dict:
    """Select the case's durable subject without materializing sibling cases."""
    requirement_id = int(case["requirement_id"])
    if case.get("starting_state") == "inherit":
        raise QaCaseExecutionError(
            f"qa_single_{kind}_inherits: this case requires its predecessor in the same execution; "
            "run its attached plan with `yoke qa plan run --help` for the subject flags"
        )
    if case.get("standalone_execution_id"):
        raise QaCaseExecutionError(_standalone_refusal(case, kind))
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
            f"qa_single_{kind}_start_failed: {exc}. Preserve this receipt; "
            f"retry `yoke qa case run --requirement-id {requirement_id}` after the named recovery. "
            "If the server rejects requirement_id, update the serving Yoke release before retrying."
        ) from exc
