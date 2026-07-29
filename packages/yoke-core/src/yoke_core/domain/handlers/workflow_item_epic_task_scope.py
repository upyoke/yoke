"""Registered generated-task scope finalization and repair operations."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_core.domain.epic_task_scope import (
    TaskScopeIncomplete,
    finalize_generated_task_scopes,
    repair_legacy_task_scopes,
    set_no_files_scope,
)


_OWNER = "yoke_core.domain.handlers.workflow_item_epic_task_scope"


class EmptyRequest(BaseModel):
    pass


class LegacyRepairRequest(BaseModel):
    tenant_id: str = "current"


class ScopeResponse(BaseModel):
    epic_id: int
    task_num: int | None = None
    message: str
    diagnostics: list[str] = Field(default_factory=list)


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


def handle_no_files(request: FunctionCallRequest) -> HandlerOutcome:
    target = _target(request)
    if target is None or target[1] is None:
        return _bad("target must carry epic_id + task_num")
    epic_id, task_num = target
    try:
        EmptyRequest.model_validate(request.payload)
        with _connect() as conn:
            set_no_files_scope(conn, epic_id, task_num)
    except (LookupError, TaskScopeIncomplete, ValueError) as exc:
        return _bad(str(exc))
    return HandlerOutcome(
        result_payload=ScopeResponse(
            epic_id=epic_id,
            task_num=task_num,
            message=f"YOK-{epic_id} task {task_num} scope set to no_files",
        ).model_dump(),
        primary_success=True,
    )


def handle_finalize(request: FunctionCallRequest) -> HandlerOutcome:
    target = _target(request)
    if target is None:
        return _bad("target must carry epic_id")
    epic_id, _task_num = target
    try:
        EmptyRequest.model_validate(request.payload)
        with _connect() as conn:
            finalize_generated_task_scopes(conn, epic_id)
    except (TaskScopeIncomplete, ValueError) as exc:
        return _bad(str(exc))
    return HandlerOutcome(
        result_payload=ScopeResponse(
            epic_id=epic_id,
            message=f"YOK-{epic_id} generated task scopes finalized",
        ).model_dump(),
        primary_success=True,
    )


def handle_repair_legacy(request: FunctionCallRequest) -> HandlerOutcome:
    target = _target(request)
    if target is None:
        return _bad("target must carry epic_id")
    epic_id, _task_num = target
    try:
        payload = LegacyRepairRequest.model_validate(request.payload)
        with _connect() as conn:
            report = repair_legacy_task_scopes(
                conn,
                tenant_id=payload.tenant_id,
                item_id=epic_id,
            )
    except (TaskScopeIncomplete, ValueError) as exc:
        return _bad(str(exc))
    return HandlerOutcome(
        result_payload=ScopeResponse(
            epic_id=epic_id,
            message=(
                f"YOK-{epic_id} legacy task scopes typed: "
                f"{len(report.path_tasks)} paths, "
                f"{len(report.deferred_tasks)} deferred"
            ),
            diagnostics=list(report.diagnostics),
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
        "emitted_event_names": ["YokeFunctionCalled"],
        "guardrails": [],
        "adapter_status": "live",
        "claim_required_kind": "epic",
    }


REGISTRATIONS = [
    _entry(
        "workflow_item.epic_task.scope_no_files",
        handle_no_files,
        EmptyRequest,
    ),
    _entry(
        "workflow_item.epic_task.scope_finalize",
        handle_finalize,
        EmptyRequest,
    ),
    _entry(
        "workflow_item.epic_task.scope_repair_legacy",
        handle_repair_legacy,
        LegacyRepairRequest,
    ),
]


__all__ = ["REGISTRATIONS"]
