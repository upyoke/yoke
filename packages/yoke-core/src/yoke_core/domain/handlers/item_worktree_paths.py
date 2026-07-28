"""Registered active-lane listing and machine-local path recording."""

from __future__ import annotations

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_core.domain.handlers.item_worktrees import ItemWorktreeLane
from yoke_core.domain.workflow_item_binding_validation import (
    WorkflowItemBindingError,
)


class ItemWorktreesListRequest(BaseModel):
    pass


class ItemWorktreesListResponse(BaseModel):
    item_id: int
    worktrees: list[ItemWorktreeLane]


class ItemWorktreePathRecordRequest(BaseModel):
    path: str = Field(..., min_length=1)


class ItemWorktreePathRecordPreconditions(BaseModel):
    worktree_id: int
    branch: str = Field(..., min_length=1)


class ItemWorktreePathRecordResponse(BaseModel):
    item_id: int
    worktree: ItemWorktreeLane


def _error(
    code: str,
    message: str,
    *,
    jsonpath: str | None = None,
) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath=jsonpath),
    )


def _item_id(request: FunctionCallRequest) -> int | None:
    target = request.target
    if target.kind != "item" or target.item_id is None:
        return None
    return int(target.item_id)


def handle_list(request: FunctionCallRequest) -> HandlerOutcome:
    """Return every active lane without collapsing repeated worker roles."""
    item_id = _item_id(request)
    if item_id is None:
        return _error(
            "target_invalid",
            "item_worktrees.list requires target.kind='item' with item_id",
        )
    try:
        ItemWorktreesListRequest.model_validate(request.payload or {})
    except Exception as exc:
        return _error("payload_invalid", f"list payload invalid: {exc}")

    from yoke_core.domain import db_helpers
    from yoke_core.domain.item_worktrees import list_item_worktrees

    with db_helpers.connect() as conn:
        lanes = list_item_worktrees(conn, item_id, active_only=True)
    response = ItemWorktreesListResponse(
        item_id=item_id,
        worktrees=[ItemWorktreeLane.model_validate(lane) for lane in lanes],
    )
    return HandlerOutcome(
        result_payload=response.model_dump(),
        primary_success=True,
    )


def handle_path_record(request: FunctionCallRequest) -> HandlerOutcome:
    """Record a path only while the named active lane and branch still match."""
    item_id = _item_id(request)
    if item_id is None:
        return _error(
            "target_invalid",
            "item_worktrees.path_record requires target.kind='item' with item_id",
        )
    try:
        payload = ItemWorktreePathRecordRequest.model_validate(
            request.payload or {},
        )
    except Exception as exc:
        return _error(
            "payload_invalid",
            f"path-record payload invalid: {exc}",
            jsonpath="$.payload",
        )
    try:
        expected = ItemWorktreePathRecordPreconditions.model_validate(
            request.preconditions or {},
        )
    except Exception as exc:
        return _error(
            "precondition_invalid",
            f"path-record preconditions invalid: {exc}",
            jsonpath="$.preconditions",
        )

    from yoke_core.domain import db_helpers
    from yoke_core.domain.item_worktree_path_recording import (
        record_item_worktree_path,
    )

    try:
        with db_helpers.connect() as conn:
            lane = record_item_worktree_path(
                conn,
                item_id=item_id,
                worktree_id=expected.worktree_id,
                expected_branch=expected.branch,
                path=payload.path,
            )
            conn.commit()
    except WorkflowItemBindingError as exc:
        code = "not_found" if "does not exist" in str(exc) else "item_inactive"
        return _error(code, str(exc))
    except ValueError as exc:
        message = str(exc)
        code = (
            "lane_precondition_stale"
            if "no longer active" in message or "branch changed" in message
            else "path_record_refused"
        )
        return _error(code, message)

    response = ItemWorktreePathRecordResponse(
        item_id=item_id,
        worktree=ItemWorktreeLane.model_validate(lane),
    )
    return HandlerOutcome(
        result_payload=response.model_dump(),
        primary_success=True,
    )


__all__ = [
    "ItemWorktreePathRecordPreconditions",
    "ItemWorktreePathRecordRequest",
    "ItemWorktreePathRecordResponse",
    "ItemWorktreesListRequest",
    "ItemWorktreesListResponse",
    "handle_list",
    "handle_path_record",
]
