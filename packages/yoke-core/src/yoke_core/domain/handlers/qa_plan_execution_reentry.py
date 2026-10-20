"""Registered pause and exact-execution re-entry authority."""

from pydantic import Field

from yoke_contracts.api.function_call import HandlerOutcome
from yoke_core.domain.handlers.qa_plan_execution import _owned_execution, _parse, _error
from yoke_core.domain.handlers.qa_plan_execution_models import (
    PlanExecutionStateRequest,
    PlanExecutionBeginRequest,
)


class PlanExecutionPauseRequest(PlanExecutionStateRequest):
    phase: str = Field(pattern="^(checkin|case|recording|review)$")
    cursor: int = Field(ge=0)
    request_id: str = Field(min_length=1)
    attempts: list[dict] = Field(max_length=2)
    evidence_path: str | None = None
    capture_path: str | None = None


class PlanExecutionResumeRequest(PlanExecutionBeginRequest):
    execution_id: str = Field(min_length=1)


def require_resume_inputs(conn, execution, parsed):
    from yoke_core.domain.qa_plan_execution_roster import validate_roster_machine
    from yoke_core.domain.qa_standalone_context import require_same_source
    from yoke_core.domain.item_ref_resolution import resolve_item_ref_or_none

    for key in ("transition_id", "deployment_stage"):
        if getattr(parsed, key) != execution.get(key):
            raise ValueError(
                f"qa_resume_subject_mismatch: use the execution's original {key}"
            )
    member = (
        resolve_item_ref_or_none(conn, parsed.deployment_member)
        if parsed.deployment_member
        else None
    )
    # Shared execution identity intentionally omits the attaching member.
    target = execution.get("execution_target") or {}
    shared = (target.get("deployment") or {}).get("shared_plan")
    if shared and member is not None:
        from yoke_core.domain.deployment_qa_shared_plans import resolve_shared_subject

        resolve_shared_subject(
            conn,
            run_id=str(execution["deployment_run_id"]),
            stage_name=str(execution["deployment_stage"]),
            plan_id=int(shared["plan_id"]),
            member_item_id=member,
            expected_target=target,
        )
    if not shared and member != execution.get("deployment_member_item_id"):
        raise ValueError(
            "qa_resume_subject_mismatch: use the execution's original member"
        )
    if parsed.plan and execution.get("standalone_plan_id"):
        row = conn.execute(
            "SELECT id FROM qa_plans WHERE id=%s AND (slug=%s OR CAST(id AS TEXT)=%s)",
            (execution["standalone_plan_id"], parsed.plan, parsed.plan),
        ).fetchone()
        if row is None:
            raise ValueError(
                "qa_resume_subject_mismatch: use the execution's original plan"
            )
    validate_roster_machine(conn, execution["roster"], parsed.machine)
    require_same_source(
        execution["roster"],
        source_revision=parsed.source_revision,
        source_ref=parsed.source_ref,
        checkout_path=parsed.checkout_path,
    )


def handle_execution_reentry(request):
    pausing = request.function == "qa.plan_execution.pause"
    parsed = _parse(
        PlanExecutionPauseRequest if pausing else PlanExecutionResumeRequest,
        request.payload,
    )
    if isinstance(parsed, HandlerOutcome):
        return parsed
    owned = _owned_execution(request, parsed)
    if isinstance(owned, HandlerOutcome):
        return owned
    conn, execution = owned
    try:
        from yoke_core.domain.qa_plan_execution_reentry import (
            pause_execution,
            resume_execution,
        )

        if pausing:
            result = pause_execution(
                conn, execution, **parsed.model_dump(exclude={"execution_id"})
            )
        else:
            require_resume_inputs(conn, execution, parsed)
            result = resume_execution(conn, execution)
            if execution.get("deployment_stage"):
                from yoke_core.domain.deployment_qa_start_identity import (
                    START_IDENTITY_FIELD,
                    start_identity_expectation,
                )

                result[START_IDENTITY_FIELD] = start_identity_expectation(
                    conn, execution
                )
    except ValueError as exc:
        conn.rollback()
        return _error("plan_execution_reentry_refused", str(exc), "$.payload")
    finally:
        conn.close()
    return HandlerOutcome(primary_success=True, result_payload=result)
