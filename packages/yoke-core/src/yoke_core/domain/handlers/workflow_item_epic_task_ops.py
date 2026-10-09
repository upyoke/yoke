"""Typed handlers for epic task reads and dispatch-chain state operations."""

from __future__ import annotations

from functools import partial
from typing import Any, Dict, List, Optional, Tuple

from yoke_core.domain import epic
from yoke_core.domain.dispatch_chain_head import read_head_dispatch
from yoke_core.domain.epic_parsing import public_epic_pipe_rows
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)

from yoke_core.domain.handlers.epic_task_operation_models import (
    operation_registration,
    EmptyRequest as EmptyRequest,
    PhaseRequest as PhaseRequest,
    FileAddRequest as FileAddRequest,
    HistoryInsertRequest as HistoryInsertRequest,
    ChainWorktreeRequest as ChainWorktreeRequest,
    ChainUpdateRequest as ChainUpdateRequest,
    ChainRefreshActivationRequest as ChainRefreshActivationRequest,
    BodyResponse as BodyResponse,
    ChainReadResponse as ChainReadResponse,
    TaskBodyResponse as TaskBodyResponse,
    MessageResponse as MessageResponse,
)

_OWNER = "yoke_core.domain.handlers.workflow_item_epic_task_ops"


def _bad(message: str) -> HandlerOutcome:
    return HandlerOutcome(
        result_payload={},
        primary_success=False,
        error=FunctionError(code="invalid_payload", message=message),
    )


def _not_found(message: str) -> HandlerOutcome:
    return HandlerOutcome(
        result_payload={},
        primary_success=False,
        error=FunctionError(code="target_not_found", message=message),
    )


def _open_connection():
    from yoke_core.domain import db_helpers

    return db_helpers.connect()


def _task_target(request: FunctionCallRequest) -> Optional[Tuple[int, int]]:
    target = request.target
    if target.kind != "epic_task" or target.epic_id is None or target.task_num is None:
        return None
    return int(target.epic_id), int(target.task_num)


def _epic_id(request: FunctionCallRequest) -> Optional[int]:
    target = request.target
    if target.kind != "epic_task" or target.epic_id is None:
        return None
    return int(target.epic_id)


def _validate(
    model: Any, payload: Dict[str, Any]
) -> Tuple[Any, Optional[HandlerOutcome]]:
    try:
        return model.model_validate(payload), None
    except Exception as exc:
        return None, _bad(f"payload invalid: {exc}")


def handle_task_get(request: FunctionCallRequest) -> HandlerOutcome:
    ids = _task_target(request)
    if ids is None:
        return _bad("target must carry public_ref + task_num")
    _, err = _validate(EmptyRequest, request.payload)
    if err:
        return err
    epic_id, task_num = ids
    with _open_connection() as conn:
        try:
            body = public_epic_pipe_rows(
                conn, epic_id, epic.task_get(conn, str(epic_id), task_num)
            )
        except LookupError as exc:
            return _not_found(str(exc))
    return HandlerOutcome(
        result_payload=TaskBodyResponse(
            epic_id=epic_id,
            task_num=task_num,
            body=body,
        ).model_dump(),
        primary_success=True,
    )


def handle_simulation_get(request: FunctionCallRequest) -> HandlerOutcome:
    epic_id = _epic_id(request)
    if epic_id is None:
        return _bad("target must carry public_ref")
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
        return _bad("target must carry public_ref + task_num")
    payload, err = _validate(FileAddRequest, request.payload)
    if err:
        return err
    epic_id, task_num = ids
    with _open_connection() as conn:
        message = epic.file_add(
            conn,
            str(epic_id),
            task_num,
            payload.file_path,
            payload.action,
        )
    return HandlerOutcome(
        result_payload=MessageResponse(
            epic_id=epic_id,
            task_num=task_num,
            message=message,
        ).model_dump(),
        primary_success=True,
    )


def handle_history_insert(request: FunctionCallRequest) -> HandlerOutcome:
    ids = _task_target(request)
    if ids is None:
        return _bad("target must carry public_ref + task_num")
    payload, err = _validate(HistoryInsertRequest, request.payload)
    if err:
        return err
    epic_id, task_num = ids
    with _open_connection() as conn:
        message = epic.history_insert(
            conn,
            str(epic_id),
            task_num,
            payload.from_status,
            payload.to_status,
            payload.note,
        )
    return HandlerOutcome(
        result_payload=MessageResponse(
            epic_id=epic_id,
            task_num=task_num,
            message=message,
        ).model_dump(),
        primary_success=True,
    )


def handle_dispatch_chain_get(request: FunctionCallRequest) -> HandlerOutcome:
    epic_id = _epic_id(request)
    if epic_id is None:
        return _bad("target must carry public_ref")
    payload, err = _validate(ChainWorktreeRequest, request.payload)
    if err:
        return err
    with _open_connection() as conn:
        try:
            body = public_epic_pipe_rows(
                conn,
                epic_id,
                epic.dispatch_chain_get(conn, str(epic_id), payload.worktree),
            )
        except LookupError as exc:
            return _not_found(str(exc))
        heads = read_head_dispatch(
            conn, epic_id, request.actor.session_id, payload.worktree
        )
    return HandlerOutcome(
        result_payload=ChainReadResponse(
            epic_id=epic_id, body=body, head_dispatch=heads
        ).model_dump(),
        primary_success=True,
    )


def handle_dispatch_chain_list(request: FunctionCallRequest) -> HandlerOutcome:
    epic_id = _epic_id(request)
    if epic_id is None:
        return _bad("target must carry public_ref")
    _, err = _validate(EmptyRequest, request.payload)
    if err:
        return err
    with _open_connection() as conn:
        body = public_epic_pipe_rows(
            conn, epic_id, epic.dispatch_chain_list(conn, str(epic_id))
        )
        heads = read_head_dispatch(conn, epic_id, request.actor.session_id)
    return HandlerOutcome(
        result_payload=ChainReadResponse(
            epic_id=epic_id, body=body, head_dispatch=heads
        ).model_dump(),
        primary_success=True,
    )


def handle_dispatch_chain_update(request: FunctionCallRequest) -> HandlerOutcome:
    epic_id = _epic_id(request)
    if epic_id is None:
        return _bad("target must carry public_ref")
    payload, err = _validate(ChainUpdateRequest, request.payload)
    if err:
        return err
    with _open_connection() as conn:
        try:
            message = epic.dispatch_chain_update(
                conn,
                str(epic_id),
                payload.worktree,
                payload.field,
                payload.value,
            )
        except LookupError as exc:
            return _not_found(str(exc))
        except ValueError as exc:
            return _bad(str(exc))
    return HandlerOutcome(
        result_payload=MessageResponse(
            epic_id=epic_id,
            message=message,
        ).model_dump(),
        primary_success=True,
    )


def handle_dispatch_chain_refresh_activation(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    epic_id = _epic_id(request)
    if epic_id is None:
        return _bad("target must carry public_ref")
    payload, err = _validate(ChainRefreshActivationRequest, request.payload)
    if err:
        return err
    with _open_connection() as conn:
        try:
            message = epic.dispatch_chain_refresh_for_activation(
                conn,
                str(epic_id),
                payload.worktree,
                str(payload.task_num),
            )
        except LookupError as exc:
            return _not_found(str(exc))
    return HandlerOutcome(
        result_payload=MessageResponse(
            epic_id=epic_id,
            task_num=payload.task_num,
            message=message,
        ).model_dump(),
        primary_success=True,
    )


_entry = partial(operation_registration, owner=_OWNER)

REGISTRATIONS: List[Dict[str, Any]] = [
    _entry(
        "workflow_item.epic_task.get",
        handle_task_get,
        EmptyRequest,
        TaskBodyResponse,
        [],
        None,
    ),
    _entry(
        "workflow_item.epic_task.simulation_get",
        handle_simulation_get,
        PhaseRequest,
        BodyResponse,
        [],
        None,
    ),
    _entry(
        "workflow_item.epic_task.file_add",
        handle_file_add,
        FileAddRequest,
        MessageResponse,
        ["epic_task_files_write"],
        "epic",
    ),
    _entry(
        "workflow_item.epic_task.history_insert",
        handle_history_insert,
        HistoryInsertRequest,
        MessageResponse,
        ["task_status_history_insert", "event_emit"],
        "epic",
    ),
    _entry(
        "workflow_item.epic_dispatch_chain.get",
        handle_dispatch_chain_get,
        ChainWorktreeRequest,
        ChainReadResponse,
        [],
        None,
    ),
    _entry(
        "workflow_item.epic_dispatch_chain.list",
        handle_dispatch_chain_list,
        EmptyRequest,
        ChainReadResponse,
        [],
        None,
    ),
    _entry(
        "workflow_item.epic_dispatch_chain.update",
        handle_dispatch_chain_update,
        ChainUpdateRequest,
        MessageResponse,
        ["epic_dispatch_chains_update"],
        "epic",
    ),
    _entry(
        "workflow_item.epic_dispatch_chain.refresh_activation",
        handle_dispatch_chain_refresh_activation,
        ChainRefreshActivationRequest,
        MessageResponse,
        ["epic_dispatch_chains_update"],
        "epic",
    ),
]

__all__ = ["REGISTRATIONS"]
