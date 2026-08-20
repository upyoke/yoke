"""Handlers for the ``workflow.execution_instruction.*`` function family.

Create, update, set-scope, resolve, list, and delete operator-authored
execution instructions. Every mutation emits an audited event carrying the
acting session and actor identity.
"""

from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel, Field

from yoke_core.domain import events as _events
from yoke_core.domain import workflow_execution_instructions as _instructions
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)

INSTRUCTION_CREATED_EVENT = "WorkflowExecutionInstructionCreated"
INSTRUCTION_UPDATED_EVENT = "WorkflowExecutionInstructionUpdated"
INSTRUCTION_SCOPE_SET_EVENT = "WorkflowExecutionInstructionScopeSet"
INSTRUCTION_DELETED_EVENT = "WorkflowExecutionInstructionDeleted"


class InstructionCreateRequest(BaseModel):
    content: str = Field(..., min_length=1)


class InstructionUpdateRequest(BaseModel):
    instruction_id: int = Field(..., gt=0)
    content: str = Field(..., min_length=1)


class InstructionSetScopeRequest(BaseModel):
    instruction_id: int = Field(..., gt=0)
    applies_to_all_workflows: bool = False
    workflow_ids: list[str] = Field(default_factory=list)
    applies_to_all_projects: bool = False
    project_ids: list[int] = Field(default_factory=list)


class InstructionListRequest(BaseModel):
    pass


class InstructionResolveRequest(BaseModel):
    workflow: str = Field(..., min_length=1)
    project: str = Field(..., min_length=1)


class InstructionDeleteRequest(BaseModel):
    instruction_id: int = Field(..., gt=0)


class InstructionIdResponse(BaseModel):
    instruction_id: int


class InstructionListResponse(BaseModel):
    instructions: list[dict[str, Any]]


class InstructionResolveResponse(BaseModel):
    execution_instructions: list[dict[str, Any]]


def _error(code: str, message: str, jsonpath: str | None = None) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath=jsonpath),
    )


def _numeric_actor_id(actor_id: Any) -> int | None:
    try:
        return int(actor_id) if actor_id is not None else None
    except (TypeError, ValueError):
        return None


def _emit(event_name: str, request: FunctionCallRequest, context: Dict[str, Any]) -> None:
    _events.emit_event(
        event_name,
        event_kind="workflow",
        event_type="execution_instruction",
        source_type="agent",
        session_id=request.actor.session_id or "",
        severity="INFO",
        outcome="completed",
        context={"actor_id": _numeric_actor_id(request.actor.actor_id), **context},
    )


def _validated(request: FunctionCallRequest, model: type[BaseModel]):
    try:
        return model.model_validate(request.payload or {}), None
    except Exception as exc:
        return None, _error("payload_invalid", str(exc), "$.payload")


def handle_instruction_create(request: FunctionCallRequest) -> HandlerOutcome:
    payload, err = _validated(request, InstructionCreateRequest)
    if err is not None:
        return err
    from yoke_core.domain.db_helpers import connect

    with connect() as conn:
        try:
            instruction_id = _instructions.create_instruction(
                conn,
                content=payload.content,
                actor_id=_numeric_actor_id(request.actor.actor_id),
            )
        except _instructions.EmptyExecutionInstructionError as exc:
            return _error("empty_content_refused", str(exc))
        conn.commit()
    _emit(
        INSTRUCTION_CREATED_EVENT,
        request,
        {"instruction_id": instruction_id},
    )
    return HandlerOutcome(
        result_payload={"instruction_id": instruction_id}, primary_success=True
    )


def handle_instruction_update(request: FunctionCallRequest) -> HandlerOutcome:
    payload, err = _validated(request, InstructionUpdateRequest)
    if err is not None:
        return err
    from yoke_core.domain.db_helpers import connect

    with connect() as conn:
        try:
            _instructions.update_instruction(
                conn,
                payload.instruction_id,
                content=payload.content,
                actor_id=_numeric_actor_id(request.actor.actor_id),
            )
        except _instructions.UnknownExecutionInstructionError as exc:
            return _error("not_found", str(exc))
        except _instructions.EmptyExecutionInstructionError as exc:
            return _error("empty_content_refused", str(exc))
        conn.commit()
    _emit(
        INSTRUCTION_UPDATED_EVENT,
        request,
        {"instruction_id": payload.instruction_id},
    )
    return HandlerOutcome(
        result_payload={"instruction_id": payload.instruction_id},
        primary_success=True,
    )


def handle_instruction_set_scope(request: FunctionCallRequest) -> HandlerOutcome:
    payload, err = _validated(request, InstructionSetScopeRequest)
    if err is not None:
        return err
    from yoke_core.domain.db_helpers import connect

    with connect() as conn:
        try:
            _instructions.set_instruction_scope(
                conn,
                payload.instruction_id,
                applies_to_all_workflows=payload.applies_to_all_workflows,
                workflow_ids=payload.workflow_ids,
                applies_to_all_projects=payload.applies_to_all_projects,
                project_ids=payload.project_ids,
                actor_id=_numeric_actor_id(request.actor.actor_id),
            )
        except _instructions.UnknownExecutionInstructionError as exc:
            return _error("not_found", str(exc))
        conn.commit()
    _emit(
        INSTRUCTION_SCOPE_SET_EVENT,
        request,
        {
            "instruction_id": payload.instruction_id,
            "applies_to_all_workflows": payload.applies_to_all_workflows,
            "workflow_ids": payload.workflow_ids,
            "applies_to_all_projects": payload.applies_to_all_projects,
            "project_ids": payload.project_ids,
        },
    )
    return HandlerOutcome(
        result_payload={"instruction_id": payload.instruction_id},
        primary_success=True,
    )


def handle_instruction_list(request: FunctionCallRequest) -> HandlerOutcome:
    _, err = _validated(request, InstructionListRequest)
    if err is not None:
        return err
    from yoke_core.domain.db_helpers import connect

    with connect() as conn:
        instructions = _instructions.list_instructions(conn)
    return HandlerOutcome(
        result_payload={"instructions": instructions}, primary_success=True
    )


def handle_instruction_resolve(request: FunctionCallRequest) -> HandlerOutcome:
    payload, err = _validated(request, InstructionResolveRequest)
    if err is not None:
        return err
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.project_identity import resolve_project_id

    with connect() as conn:
        try:
            project_id = resolve_project_id(conn, payload.project)
        except LookupError as exc:
            return _error("not_found", str(exc), "$.payload.project")
        instructions = _instructions.resolve_execution_instructions(
            conn, workflow_id=payload.workflow, project_id=project_id
        )
    return HandlerOutcome(
        result_payload={"execution_instructions": instructions},
        primary_success=True,
    )


def handle_instruction_delete(request: FunctionCallRequest) -> HandlerOutcome:
    payload, err = _validated(request, InstructionDeleteRequest)
    if err is not None:
        return err
    from yoke_core.domain.db_helpers import connect

    with connect() as conn:
        try:
            _instructions.delete_instruction(conn, payload.instruction_id)
        except _instructions.UnknownExecutionInstructionError as exc:
            return _error("not_found", str(exc))
        conn.commit()
    _emit(
        INSTRUCTION_DELETED_EVENT,
        request,
        {"instruction_id": payload.instruction_id},
    )
    return HandlerOutcome(
        result_payload={"instruction_id": payload.instruction_id},
        primary_success=True,
    )


def _registration(
    operation: str,
    handler: Any,
    request_model: type[BaseModel],
    response_model: type[BaseModel],
    *,
    write: bool,
    event_name: str | None,
) -> Dict[str, Any]:
    return {
        "function_id": f"workflow.execution_instruction.{operation}",
        "handler": handler,
        "request_model": request_model,
        "response_model": response_model,
        "stability": "stable",
        "owner_module": (
            "yoke_core.domain.handlers.workflow_execution_instructions_crud"
        ),
        "target_kinds": ["global"],
        # Reads declare no side effects: the UI proxy's read allowlist
        # admits only entries the registry itself reports as read-only.
        "side_effects": ["db_write", "event_emit"] if write else [],
        "emitted_event_names": [event_name] if event_name else [],
        "guardrails": ["empty_content_refused"] if write else [],
        "adapter_status": "live",
        "claim_required_kind": None,
        "ambient_session_required": False,
    }


REGISTRATIONS: List[Dict[str, Any]] = [
    _registration(
        "create",
        handle_instruction_create,
        InstructionCreateRequest,
        InstructionIdResponse,
        write=True,
        event_name=INSTRUCTION_CREATED_EVENT,
    ),
    _registration(
        "update",
        handle_instruction_update,
        InstructionUpdateRequest,
        InstructionIdResponse,
        write=True,
        event_name=INSTRUCTION_UPDATED_EVENT,
    ),
    _registration(
        "set_scope",
        handle_instruction_set_scope,
        InstructionSetScopeRequest,
        InstructionIdResponse,
        write=True,
        event_name=INSTRUCTION_SCOPE_SET_EVENT,
    ),
    _registration(
        "resolve",
        handle_instruction_resolve,
        InstructionResolveRequest,
        InstructionResolveResponse,
        write=False,
        event_name=None,
    ),
    _registration(
        "list",
        handle_instruction_list,
        InstructionListRequest,
        InstructionListResponse,
        write=False,
        event_name=None,
    ),
    _registration(
        "delete",
        handle_instruction_delete,
        InstructionDeleteRequest,
        InstructionIdResponse,
        write=True,
        event_name=INSTRUCTION_DELETED_EVENT,
    ),
]


__all__ = [
    "INSTRUCTION_CREATED_EVENT",
    "INSTRUCTION_DELETED_EVENT",
    "INSTRUCTION_SCOPE_SET_EVENT",
    "INSTRUCTION_UPDATED_EVENT",
    "REGISTRATIONS",
]
