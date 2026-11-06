"""Registered authority for ordered materialized QA plan execution."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ValidationError
from psycopg.errors import LockNotAvailable, QueryCanceled

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)

from yoke_core.domain.handlers.qa_plan_execution_models import (
    PlanExecutionBeginRequest,
    PlanExecutionStateRequest,
    PlanExecutionAdvanceRequest,
    PlanExecutionAbortRequest,
    PlanExecutionStateResponse,
)
from yoke_core.domain.handlers.machine_qa_plan_case_request import (
    target_plan_subject as _subject,
)


from yoke_core.domain.handlers.qa_plan_execution_ownership import _owned_execution


def _error(code: str, message: str, jsonpath: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath=jsonpath),
    )


def _parse(model: type[BaseModel], payload: Any) -> BaseModel | HandlerOutcome:
    try:
        return model.model_validate(payload or {})
    except ValidationError as exc:
        return _error("payload_invalid", str(exc), "$.payload")


def handle_plan_execution_begin(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    target = _subject(request, "qa.plan_execution.begin")
    if isinstance(target, HandlerOutcome):
        return target
    item_id, deployment_run_id = target
    parsed = _parse(PlanExecutionBeginRequest, request.payload)
    if isinstance(parsed, HandlerOutcome):
        return parsed
    assert isinstance(parsed, PlanExecutionBeginRequest)
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.qa_plan_empty_roster import (
        DISCHARGED_BEGIN_CODE,
        QaPlanRosterDischarged,
    )
    from yoke_core.domain.qa_plan_execution_result_state import QaPlanExecutionError
    from yoke_core.domain.qa_plan_execution_state import (
        QaPlanExecutionStateError,
        begin_plan_execution,
        plan_execution_view,
    )

    conn = connect()
    try:
        from yoke_core.domain.qa_item_deployment_request import (
            resolve_item_deployment_request,
            execution_member_id,
        )

        request = resolve_item_deployment_request(conn, request)
        item_id, deployment_run_id = (
            request.target.item_id,
            request.target.deployment_run_id,
        )
        parsed = PlanExecutionBeginRequest.model_validate(request.payload)
        member_item_id = execution_member_id(conn, parsed.deployment_member)
        if request.target.kind == "global":
            if parsed.requirement_id is not None:
                raise QaPlanExecutionStateError(
                    "qa_single_case_standalone: resume the existing standalone execution by its execution id"
                )
            from yoke_core.domain.qa_standalone_execution import (
                begin_requested_standalone_execution,
            )

            execution = begin_requested_standalone_execution(conn, request, parsed)
        else:
            if any(
                (
                    parsed.plan if item_id is not None else None,
                    parsed.source_revision,
                    parsed.source_ref,
                )
            ):
                raise QaPlanExecutionStateError(
                    "standalone_subject_invalid: source bindings require a standalone project target"
                )
            execution = begin_plan_execution(
                conn,
                item_id=item_id,
                deployment_run_id=deployment_run_id,
                transition_id=parsed.transition_id,
                requirement_id=parsed.requirement_id,
                deployment_stage=parsed.deployment_stage,
                deployment_member_item_id=member_item_id,
                checkout_path=parsed.checkout_path,
                expected_branch=parsed.expected_branch,
                test_machine=parsed.test_machine,
                continue_mission=parsed.continue_mission,
                plan=parsed.plan,
                actor_id=request.actor.actor_id,
                session_id=request.actor.session_id,
            )
        result = plan_execution_view(conn, execution)
        if execution.get("settled_review"):
            result["settled_review"] = execution["settled_review"]
        if deployment_run_id is not None and parsed.deployment_stage:
            from yoke_core.domain.deployment_qa_start_identity import (
                START_IDENTITY_FIELD,
                start_identity_expectation,
            )

            result[START_IDENTITY_FIELD] = start_identity_expectation(conn, execution)
    except QaPlanRosterDischarged as exc:
        conn.rollback()
        return _error(DISCHARGED_BEGIN_CODE, str(exc), "$.payload")
    except (QaPlanExecutionStateError, ValueError, QaPlanExecutionError) as exc:
        conn.rollback()
        return _error(
            getattr(exc, "code", "plan_execution_begin_failed"), str(exc), "$.payload"
        )
    finally:
        conn.close()
    return HandlerOutcome(primary_success=True, result_payload=result)


def handle_plan_execution_heartbeat(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    from time import monotonic
    from yoke_core.domain.qa_plan_execution_reentry import checkin_view

    started = monotonic()
    parsed = _parse(PlanExecutionStateRequest, request.payload)
    if isinstance(parsed, HandlerOutcome):
        return parsed
    owned = _owned_execution(request, parsed)
    if isinstance(owned, HandlerOutcome):
        return owned
    conn, execution = owned
    validated = monotonic()
    try:
        from yoke_core.domain.qa_plan_execution_roster_change import checkin

        checkin(conn, execution)
        result = checkin_view(execution)
        result["timings_ms"] = {
            "validation": (validated - started) * 1000,
            "liveness_write": (monotonic() - validated) * 1000,
        }
    except (ValueError, LockNotAvailable, QueryCanceled) as exc:
        conn.rollback()
        return _error(
            "plan_execution_heartbeat_failed",
            str(exc)
            if isinstance(exc, ValueError)
            else "qa_checkin_busy: liveness write exceeded its query budget; preserve custody and retry the same execution",
            "$.payload",
        )
    finally:
        conn.close()
    return HandlerOutcome(primary_success=True, result_payload=result)


def handle_plan_execution_advance(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    parsed = _parse(PlanExecutionAdvanceRequest, request.payload)
    if isinstance(parsed, HandlerOutcome):
        return parsed
    assert isinstance(parsed, PlanExecutionAdvanceRequest)
    owned = _owned_execution(request, parsed)
    if isinstance(owned, HandlerOutcome):
        return owned
    conn, execution = owned
    try:
        from yoke_core.domain.qa_plan_execution_state import (
            advance_plan_execution,
            plan_execution_view,
        )

        advance_plan_execution(
            conn,
            execution,
            ordinal=parsed.ordinal,
            requirement_id=parsed.requirement_id,
            result=parsed.result,
        )
        result = plan_execution_view(conn, execution)
    except ValueError as exc:
        conn.rollback()
        return _error("plan_execution_advance_failed", str(exc), "$.payload")
    finally:
        conn.close()
    return HandlerOutcome(primary_success=True, result_payload=result)


def _finish_execution(
    request: FunctionCallRequest,
    *,
    complete: bool,
) -> HandlerOutcome:
    model = PlanExecutionStateRequest if complete else PlanExecutionAbortRequest
    parsed = _parse(model, request.payload)
    if isinstance(parsed, HandlerOutcome):
        return parsed
    assert isinstance(parsed, PlanExecutionStateRequest)
    owned = _owned_execution(request, parsed, abandoning=not complete)
    if isinstance(owned, HandlerOutcome):
        return owned
    conn, execution = owned
    try:
        from yoke_core.domain.qa_plan_execution_state import (
            finish_plan_execution,
            plan_execution_view,
        )
        from yoke_core.domain.qa_plan_execution_stop import stop_plan_execution

        if complete:
            settlement = finish_plan_execution(
                conn, execution, state="completed", reason="qa-plan-execution-complete"
            )
            result = plan_execution_view(conn, execution)
            if settlement and settlement.get("settlement") == "deferred":
                result.update(settlement)
        else:
            result = stop_plan_execution(
                conn,
                execution,
                actor_id=request.actor.actor_id,
                session_id=request.actor.session_id,
                reason=str(getattr(parsed, "reason")),
            )
    except (ValueError, LockNotAvailable, QueryCanceled) as exc:
        from yoke_core.domain.qa_plan_execution_reentry import bounded_refusal

        conn.rollback()
        message = bounded_refusal(exc, step="execution finish")
        return _error(
            getattr(exc, "code", "plan_execution_finish_failed"), message, "$.payload"
        )
    finally:
        conn.close()
    return HandlerOutcome(primary_success=True, result_payload=result)


def handle_plan_execution_complete(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    return _finish_execution(request, complete=True)


def handle_plan_execution_abort(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    return _finish_execution(request, complete=False)


__all__ = [
    "PlanExecutionAbortRequest",
    "PlanExecutionAdvanceRequest",
    "PlanExecutionBeginRequest",
    "PlanExecutionStateRequest",
    "PlanExecutionStateResponse",
    "handle_plan_execution_abort",
    "handle_plan_execution_advance",
    "handle_plan_execution_begin",
    "handle_plan_execution_complete",
    "handle_plan_execution_heartbeat",
]
