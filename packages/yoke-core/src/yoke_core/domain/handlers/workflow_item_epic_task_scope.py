"""Registered generated-task scope finalization operations."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_core.domain.epic_task_scope import (
    TaskScopeIncomplete,
    finalize_generated_task_scopes,
    reopen_generated_task_scopes,
)
from yoke_core.domain.project_identity import render_item_ref


_OWNER = "yoke_core.domain.handlers.workflow_item_epic_task_scope"


class EmptyRequest(BaseModel):
    pass


class ScopeResponse(BaseModel):
    epic_id: int
    task_num: int | None = None
    message: str


def _bad(message: str) -> HandlerOutcome:
    return HandlerOutcome(
        result_payload={},
        primary_success=False,
        error=FunctionError(code="task_scope_incomplete", message=message),
    )


def _target(request: FunctionCallRequest) -> tuple[int, int | None] | None:
    target = request.target
    if target.kind != "epic_task" or target.epic_id is None:
        return None
    return int(target.epic_id), (
        int(target.task_num) if target.task_num is not None else None
    )


def _connect():
    from yoke_core.domain.db_helpers import connect

    return connect()


def handle_finalize(request: FunctionCallRequest) -> HandlerOutcome:
    target = _target(request)
    if target is None:
        return _bad("target must carry public_ref")
    epic_id, _task_num = target
    try:
        EmptyRequest.model_validate(request.payload)
        with _connect() as conn:
            finalize_generated_task_scopes(conn, epic_id)
            epic_ref = render_item_ref(conn, epic_id)
    except (TaskScopeIncomplete, ValueError) as exc:
        return _bad(str(exc))
    return HandlerOutcome(
        result_payload=ScopeResponse(
            epic_id=epic_id,
            message=f"{epic_ref} generated task scopes finalized",
        ).model_dump(),
        primary_success=True,
    )


def handle_reopen(request: FunctionCallRequest) -> HandlerOutcome:
    target = _target(request)
    if target is None:
        return _bad("target must carry public_ref")
    epic_id, _task_num = target
    try:
        EmptyRequest.model_validate(request.payload)
        with _connect() as conn:
            changed = reopen_generated_task_scopes(conn, epic_id)
            epic_ref = render_item_ref(conn, epic_id)
    except (LookupError, TaskScopeIncomplete, ValueError) as exc:
        return _bad(str(exc))
    return HandlerOutcome(
        result_payload=ScopeResponse(
            epic_id=epic_id,
            message=(
                f"{epic_ref} task membership reopened"
                if changed
                else f"{epic_ref} task membership was not finalized"
            ),
        ).model_dump(),
        primary_success=True,
    )


def _entry(
    function_id: str,
    handler: Any,
    request_model: Any,
) -> dict[str, Any]:
    return {
        "function_id": function_id,
        "handler": handler,
        "request_model": request_model,
        "response_model": ScopeResponse,
        "stability": "stable",
        "owner_module": _OWNER,
        "target_kinds": ["epic_task"],
        "side_effects": ["epic_task_scope_write"],
        "guardrails": [],
        "adapter_status": "live",
        "claim_required_kind": "epic",
    }


REGISTRATIONS = [
    _entry(
        "workflow_item.epic_task.scope_finalize",
        handle_finalize,
        EmptyRequest,
    ),
    _entry(
        "workflow_item.epic_task.scope_reopen",
        handle_reopen,
        EmptyRequest,
    ),
]


__all__ = ["REGISTRATIONS"]
