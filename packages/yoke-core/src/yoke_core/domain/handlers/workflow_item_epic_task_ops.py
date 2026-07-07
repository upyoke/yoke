"""Registered epic task + dispatch-chain state operations.

These handlers cover the remaining everyday ``db_router epic`` task,
simulation, file, history, and dispatch-chain operations used by
``/yoke amend`` and ``/yoke conduct``. Business rules stay in
``yoke_core.domain.epic``; this module only gives those owners typed
function-call envelopes.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from yoke_core.domain import epic
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


_OWNER = "yoke_core.domain.handlers.workflow_item_epic_task_ops"


class EmptyRequest(BaseModel):
    """No payload."""


class PhaseRequest(BaseModel):
    phase: str = Field(..., min_length=1)


class FileAddRequest(BaseModel):
    file_path: str = Field(..., min_length=1)
    action: str = ""


class HistoryInsertRequest(BaseModel):
    from_status: str = Field(..., min_length=1)
    to_status: str = Field(..., min_length=1)
    note: str = ""


class ChainWorktreeRequest(BaseModel):
    worktree: str = Field(..., min_length=1)


class ChainUpdateRequest(BaseModel):
    worktree: str = Field(..., min_length=1)
    field: str = Field(..., min_length=1)
    value: str = ""


class ChainRefreshActivationRequest(BaseModel):
    worktree: str = Field(..., min_length=1)
    task_num: int = Field(..., ge=1)


class BodyResponse(BaseModel):
    epic_id: int
    body: str


class TaskBodyResponse(BodyResponse):
    task_num: int


class MessageResponse(BaseModel):
    epic_id: int
    task_num: Optional[int] = None
    message: str


def _bad(message: str) -> HandlerOutcome:
    return HandlerOutcome(
        result_payload={}, primary_success=False,
        error=FunctionError(code="invalid_payload", message=message),
    )


def _not_found(message: str) -> HandlerOutcome:
    return HandlerOutcome(
        result_payload={}, primary_success=False,
        error=FunctionError(code="target_not_found", message=message),
    )


def _open_connection():
    from yoke_core.domain import db_helpers
    return db_helpers.connect()


def _task_target(request: FunctionCallRequest) -> Optional[Tuple[int, int]]:
    target = request.target
    if (
        target.kind != "epic_task"
        or target.epic_id is None
        or target.task_num is None
    ):
        return None
    return int(target.epic_id), int(target.task_num)


def _epic_id(request: FunctionCallRequest) -> Optional[int]:
    target = request.target
    if target.kind != "epic_task" or target.epic_id is None:
        return None
    return int(target.epic_id)


def _validate(model: Any, payload: Dict[str, Any]) -> Tuple[Any, Optional[HandlerOutcome]]:
    try:
        return model.model_validate(payload), None
    except Exception as exc:
        return None, _bad(f"payload invalid: {exc}")


def handle_task_get(request: FunctionCallRequest) -> HandlerOutcome:
    ids = _task_target(request)
    if ids is None:
        return _bad("target must carry epic_id + task_num")
    _, err = _validate(EmptyRequest, request.payload)
    if err:
        return err
    epic_id, task_num = ids
    with _open_connection() as conn:
        try:
            body = epic.task_get(conn, str(epic_id), task_num)
        except LookupError as exc:
            return _not_found(str(exc))
    return HandlerOutcome(
        result_payload=TaskBodyResponse(
            epic_id=epic_id, task_num=task_num, body=body,
        ).model_dump(),
        primary_success=True,
    )


def handle_simulation_get(request: FunctionCallRequest) -> HandlerOutcome:
    epic_id = _epic_id(request)
    if epic_id is None:
        return _bad("target must carry epic_id")
    payload, err = _validate(PhaseRequest, request.payload)
    if err:
        return err
    with _open_connection() as conn:
        try:
            body = epic.simulation_get(conn, str(epic_id), payload.phase)
        except LookupError as exc:
            return _not_found(str(exc))
    return HandlerOutcome(
        result_payload=BodyResponse(epic_id=epic_id, body=body).model_dump(),
        primary_success=True,
    )


def handle_file_add(request: FunctionCallRequest) -> HandlerOutcome:
    ids = _task_target(request)
    if ids is None:
        return _bad("target must carry epic_id + task_num")
    payload, err = _validate(FileAddRequest, request.payload)
    if err:
        return err
    epic_id, task_num = ids
    with _open_connection() as conn:
        message = epic.file_add(
            conn, str(epic_id), task_num, payload.file_path, payload.action,
        )
    return HandlerOutcome(
        result_payload=MessageResponse(
            epic_id=epic_id, task_num=task_num, message=message,
        ).model_dump(),
        primary_success=True,
    )


def handle_history_insert(request: FunctionCallRequest) -> HandlerOutcome:
    ids = _task_target(request)
    if ids is None:
        return _bad("target must carry epic_id + task_num")
    payload, err = _validate(HistoryInsertRequest, request.payload)
    if err:
        return err
    epic_id, task_num = ids
    with _open_connection() as conn:
        message = epic.history_insert(
            conn, str(epic_id), task_num,
            payload.from_status, payload.to_status, payload.note,
        )
    return HandlerOutcome(
        result_payload=MessageResponse(
            epic_id=epic_id, task_num=task_num, message=message,
        ).model_dump(),
        primary_success=True,
    )


def handle_dispatch_chain_get(request: FunctionCallRequest) -> HandlerOutcome:
    epic_id = _epic_id(request)
    if epic_id is None:
        return _bad("target must carry epic_id")
    payload, err = _validate(ChainWorktreeRequest, request.payload)
    if err:
        return err
    with _open_connection() as conn:
        try:
            body = epic.dispatch_chain_get(conn, str(epic_id), payload.worktree)
        except LookupError as exc:
            return _not_found(str(exc))
    return HandlerOutcome(
        result_payload=BodyResponse(epic_id=epic_id, body=body).model_dump(),
        primary_success=True,
    )


def handle_dispatch_chain_list(request: FunctionCallRequest) -> HandlerOutcome:
    epic_id = _epic_id(request)
    if epic_id is None:
        return _bad("target must carry epic_id")
    _, err = _validate(EmptyRequest, request.payload)
    if err:
        return err
    with _open_connection() as conn:
        body = epic.dispatch_chain_list(conn, str(epic_id))
    return HandlerOutcome(
        result_payload=BodyResponse(epic_id=epic_id, body=body).model_dump(),
        primary_success=True,
    )


def handle_dispatch_chain_update(request: FunctionCallRequest) -> HandlerOutcome:
    epic_id = _epic_id(request)
    if epic_id is None:
        return _bad("target must carry epic_id")
    payload, err = _validate(ChainUpdateRequest, request.payload)
    if err:
        return err
    with _open_connection() as conn:
        try:
            message = epic.dispatch_chain_update(
                conn, str(epic_id), payload.worktree,
                payload.field, payload.value,
            )
        except LookupError as exc:
            return _not_found(str(exc))
        except ValueError as exc:
            return _bad(str(exc))
    return HandlerOutcome(
        result_payload=MessageResponse(
            epic_id=epic_id, message=message,
        ).model_dump(),
        primary_success=True,
    )


def handle_dispatch_chain_refresh_activation(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    epic_id = _epic_id(request)
    if epic_id is None:
        return _bad("target must carry epic_id")
    payload, err = _validate(ChainRefreshActivationRequest, request.payload)
    if err:
        return err
    with _open_connection() as conn:
        try:
            message = epic.dispatch_chain_refresh_for_activation(
                conn, str(epic_id), payload.worktree, str(payload.task_num),
            )
        except LookupError as exc:
            return _not_found(str(exc))
    return HandlerOutcome(
        result_payload=MessageResponse(
            epic_id=epic_id, task_num=payload.task_num, message=message,
        ).model_dump(),
        primary_success=True,
    )


def _entry(fid: str, handler: Any, req: Any, resp: Any, effects: List[str],
           claim: Optional[str]) -> Dict[str, Any]:
    return {
        "function_id": fid,
        "handler": handler,
        "request_model": req,
        "response_model": resp,
        "stability": "stable",
        "owner_module": _OWNER,
        "target_kinds": ["epic_task"],
        "side_effects": effects,
        "emitted_event_names": ["YokeFunctionCalled"],
        "guardrails": [],
        "adapter_status": "live",
        "claim_required_kind": claim,
    }


REGISTRATIONS: List[Dict[str, Any]] = [
    _entry("workflow_item.epic_task.get", handle_task_get,
           EmptyRequest, TaskBodyResponse, [], None),
    _entry("workflow_item.epic_task.simulation_get", handle_simulation_get,
           PhaseRequest, BodyResponse, [], None),
    _entry("workflow_item.epic_task.file_add", handle_file_add,
           FileAddRequest, MessageResponse, ["epic_task_files_write"], "epic"),
    _entry("workflow_item.epic_task.history_insert", handle_history_insert,
           HistoryInsertRequest, MessageResponse,
           ["task_status_history_insert", "event_emit"], "epic"),
    _entry("workflow_item.epic_dispatch_chain.get", handle_dispatch_chain_get,
           ChainWorktreeRequest, BodyResponse, [], None),
    _entry("workflow_item.epic_dispatch_chain.list", handle_dispatch_chain_list,
           EmptyRequest, BodyResponse, [], None),
    _entry("workflow_item.epic_dispatch_chain.update",
           handle_dispatch_chain_update, ChainUpdateRequest, MessageResponse,
           ["epic_dispatch_chains_update"], "epic"),
    _entry("workflow_item.epic_dispatch_chain.refresh_activation",
           handle_dispatch_chain_refresh_activation,
           ChainRefreshActivationRequest, MessageResponse,
           ["epic_dispatch_chains_update"], "epic"),
]


__all__ = ["REGISTRATIONS"]
