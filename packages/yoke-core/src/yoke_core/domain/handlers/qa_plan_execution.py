"""Registered authority for ordered materialized QA plan execution."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class PlanExecutionBeginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transition_id: str | None = Field(default=None, min_length=1)
    machine: str | None = Field(default=None, min_length=1)
    #: Resume a mission walk the stale sweep settled while its walker was
    #: parked: same roster, own runs, and no case reaches a host baseline.
    continue_mission: bool = False


class PlanExecutionStateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    execution_id: str = Field(min_length=1)


class PlanExecutionAdvanceRequest(PlanExecutionStateRequest):
    ordinal: int = Field(ge=0)
    requirement_id: int = Field(ge=1)
    result: dict[str, Any]


class PlanExecutionAbortRequest(PlanExecutionStateRequest):
    reason: str = Field(min_length=1, max_length=200)


class PlanExecutionStateResponse(BaseModel):
    execution_id: str
    item_id: int | None = None
    deployment_run_id: str | None = None
    transition_id: str | None = None
    state: str
    roster_digest: str
    cursor_ordinal: int
    machine_lease_id: int | None = None
    continues_execution_id: str | None = None
    # Absent on a row written before executions carried a target: reading and
    # abandoning such a row are supported, running one is refused by name.
    execution_target: dict[str, Any] | None = None
    execution_target_digest: str | None = None

    requirements: list[dict[str, Any]]
    results: list[dict[str, Any]]


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
    return _error(
        "target_invalid",
        f"{function_id} requires an item or deployment-run target",
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
    from yoke_core.domain.qa_plan_execution_state import (
        QaPlanExecutionStateError,
        begin_plan_execution,
        plan_execution_view,
    )

    conn = connect()
    try:
        execution = begin_plan_execution(
            conn,
            item_id=item_id,
            deployment_run_id=deployment_run_id,
            transition_id=parsed.transition_id,
            machine=parsed.machine,
            continue_mission=parsed.continue_mission,
            actor_id=request.actor.actor_id,
            session_id=request.actor.session_id,
        )
        result = plan_execution_view(conn, execution)
    except (QaPlanExecutionStateError, ValueError) as exc:
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

    subject = {
        "item_id": item_id,
        "deployment_run_id": deployment_run_id,
        "actor_id": request.actor.actor_id,
        "session_id": request.actor.session_id,
    }
    conn = connect()
    try:
        execution = lock_plan_execution(conn, parsed.execution_id)
        if abandoning:
            require_plan_execution_abandon_authority(conn, execution, **subject)
        else:
            require_plan_execution_owner(execution, **subject)

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
