"""Registered authority for ordered materialized QA plan execution."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ValidationError

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


def _error(code: str, message: str, jsonpath: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath=jsonpath),
    )


def _subject(
    request: FunctionCallRequest,
    function_id: str,
) -> tuple[int | None, str | None] | HandlerOutcome:
    if request.target.kind == "item" and request.target.item_id is not None:
        return int(request.target.item_id), None
    if request.target.kind == "deployment_run" and request.target.deployment_run_id:
        return None, str(request.target.deployment_run_id)
    if request.target.kind == "global" and request.target.project_id:
        return None, None
    return _error(
        "target_invalid",
        f"{function_id} requires an item, deployment run, or standalone project target",
        "$.target",
    )


def _parse(model: type[BaseModel], payload: Any) -> BaseModel | HandlerOutcome:
    try:
        return model.model_validate(payload or {})
    except ValidationError as exc:
        return _error("payload_invalid", str(exc), "$.payload")


def handle_plan_execution_begin(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    """Authorize first, then create or resume the durable plan cursor."""
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
        member_item_id = None
        if parsed.deployment_member is not None:
            from yoke_core.domain.item_ref_resolution import resolve_item_ref_or_none

            member_item_id = resolve_item_ref_or_none(conn, parsed.deployment_member)
            if member_item_id is None:
                raise QaPlanExecutionStateError(
                    f"deployment member {parsed.deployment_member!r} not found"
                )
        if request.target.kind == "global":
            from yoke_core.domain.qa_standalone_execution import (
                begin_requested_standalone_execution,
            )

            execution = begin_requested_standalone_execution(conn, request, parsed)
        else:
            if any(
                (
                    parsed.plan,
                    parsed.source_revision,
                    parsed.source_ref,
                    parsed.checkout_path,
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
                deployment_stage=parsed.deployment_stage,
                deployment_member_item_id=member_item_id,
                machine=parsed.machine,
                continue_mission=parsed.continue_mission,
                actor_id=request.actor.actor_id,
                session_id=request.actor.session_id,
            )
        result = plan_execution_view(conn, execution)
    except QaPlanRosterDischarged as exc:
        conn.rollback()
        return _error(DISCHARGED_BEGIN_CODE, str(exc), "$.payload")
    except (QaPlanExecutionStateError, ValueError, QaPlanExecutionError) as exc:
        conn.rollback()
        return _error("plan_execution_begin_failed", str(exc), "$.payload")
    finally:
        conn.close()
    return HandlerOutcome(primary_success=True, result_payload=result)


def _owned_execution(
    request: FunctionCallRequest,
    parsed: PlanExecutionStateRequest,
    *,
    abandoning: bool = False,
) -> tuple[Any, dict[str, Any]] | HandlerOutcome:
    target = _subject(request, request.function)
    if isinstance(target, HandlerOutcome):
        return target
    item_id, deployment_run_id = target
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.qa_plan_execution_state import (
        lock_plan_execution,
        require_plan_execution_abandon_authority,
        require_plan_execution_owner,
    )

    conn = connect()
    try:
        execution = lock_plan_execution(conn, parsed.execution_id)
        if request.target.kind == "global":
            from yoke_core.domain.qa_standalone_execution import (
                require_standalone_project,
            )

            require_standalone_project(conn, execution, str(request.target.project_id))
        subject = {
            "item_id": item_id,
            "deployment_run_id": deployment_run_id,
            "actor_id": request.actor.actor_id,
            "session_id": request.actor.session_id,
        }
        if abandoning:
            require_plan_execution_abandon_authority(conn, execution, **subject)
        else:
            require_plan_execution_owner(
                execution,
                conn=conn,
                deployment_stage=execution.get("deployment_stage"),
                deployment_member_item_id=execution.get("deployment_member_item_id"),
                **subject,
            )

    except ValueError as exc:
        conn.rollback()
        conn.close()
        return _error("plan_execution_invalid", str(exc), "$.payload.execution_id")
    return conn, execution


def handle_plan_execution_heartbeat(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    parsed = _parse(PlanExecutionStateRequest, request.payload)
    if isinstance(parsed, HandlerOutcome):
        return parsed
    assert isinstance(parsed, PlanExecutionStateRequest)
    owned = _owned_execution(request, parsed)
    if isinstance(owned, HandlerOutcome):
        return owned
    conn, execution = owned
    try:
        from yoke_core.domain.qa_plan_execution_state import (
            heartbeat_plan_execution,
            plan_execution_view,
        )

        heartbeat_plan_execution(conn, execution)
        result = plan_execution_view(conn, execution)
    except ValueError as exc:
        conn.rollback()
        return _error("plan_execution_heartbeat_failed", str(exc), "$.payload")
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

        reason = (
            "qa-plan-execution-complete" if complete else str(getattr(parsed, "reason"))
        )
        finish_plan_execution(
            conn,
            execution,
            state="completed" if complete else "aborted",
            reason=reason,
        )
        result = plan_execution_view(conn, execution)
    except ValueError as exc:
        conn.rollback()
        return _error("plan_execution_finish_failed", str(exc), "$.payload")
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
