"""Handlers for the ``workflow_item.epic_task.*`` function family.

Implements six function ids that subsume `/yoke amend` task-level
choreography:

- ``workflow_item.epic_task.body_replace``
- ``workflow_item.epic_task.split``
- ``workflow_item.epic_task.reassign``
- ``workflow_item.epic_task.add``
- ``workflow_item.epic_task.remove``
- ``workflow_item.epic_task.metadata_update``

Each handler is a thin wrapper around the existing domain owners:
``yoke_core.domain.epic_task_crud.task_update_body`` for body
replacement and ``yoke_core.domain.epic_amend`` for the five
amend-style operations. Pydantic request/response shapes live in
:mod:`workflow_item_epic_task_models` to keep this module under the
authored-file budget.

Future-concept absorption target: when the execution journal lands,
these handler bodies become journal-emit + domain-helper pairs and
this module merges into the journal hot path.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from yoke_core.domain import epic_amend, epic_task_crud
from yoke_core.domain.epic_parsing import _placeholder
from yoke_core.domain.handlers.workflow_item_epic_task_models import (
    AddRequest, AddResponse,
    BodyReplaceRequest, BodyReplaceResponse,
    MetadataUpdateRequest, MetadataUpdateResponse,
    ReassignRequest, ReassignResponse,
    RemoveRequest, RemoveResponse,
    SplitRequest, SplitResponse,
)
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _target_ids(request: FunctionCallRequest) -> Optional[Dict[str, int]]:
    target = request.target
    if target.kind != "epic_task" or target.epic_id is None:
        return None
    return {
        "epic_id": int(target.epic_id),
        "task_num": int(target.task_num) if target.task_num is not None else 0,
    }


def _not_found_outcome(message: str) -> HandlerOutcome:
    return HandlerOutcome(
        result_payload={}, primary_success=False,
        error=FunctionError(code="target_not_found", message=message),
    )


def _bad_request_outcome(message: str) -> HandlerOutcome:
    return HandlerOutcome(
        result_payload={}, primary_success=False,
        error=FunctionError(code="invalid_payload", message=message),
    )


def _open_connection():
    from yoke_core.domain import db_helpers
    return db_helpers.connect()


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def handle_body_replace(request: FunctionCallRequest) -> HandlerOutcome:
    """Replace ``epic_tasks.body`` via ``epic_task_crud.task_update_body``."""
    target = _target_ids(request)
    if target is None or target["task_num"] == 0:
        return _bad_request_outcome("target must carry epic_id + task_num")
    try:
        payload = BodyReplaceRequest.model_validate(request.payload)
    except Exception as exc:
        return _bad_request_outcome(f"payload invalid: {exc}")
    epic_key = str(target["epic_id"])
    task_num = target["task_num"]
    with _open_connection() as conn:
        p = _placeholder(conn)
        existing = conn.execute(
            f"SELECT body FROM epic_tasks WHERE epic_id = {p} AND task_num = {p}",
            (epic_key, task_num),
        ).fetchone()
        if existing is None:
            return _not_found_outcome(
                f"epic_task {epic_key}/{task_num} not found"
            )
        old_body = (
            existing[0] if not hasattr(existing, "keys") else existing["body"]
        ) or ""
        try:
            epic_task_crud.task_update_body(conn, epic_key, task_num, payload.body)
        except LookupError as exc:
            return _not_found_outcome(str(exc))
    result = BodyReplaceResponse(
        epic_id=int(epic_key), task_num=task_num,
        old_line_count=len(old_body.splitlines()),
        new_line_count=len(payload.body.splitlines()),
    )
    return HandlerOutcome(result_payload=result.model_dump(), primary_success=True)


def handle_split(request: FunctionCallRequest) -> HandlerOutcome:
    """Split a task via ``epic_amend.task_split``."""
    target = _target_ids(request)
    if target is None or target["task_num"] == 0:
        return _bad_request_outcome("target must carry epic_id + task_num")
    try:
        payload = SplitRequest.model_validate(request.payload)
    except Exception as exc:
        return _bad_request_outcome(f"payload invalid: {exc}")
    children = [c.model_dump() for c in payload.children]
    with _open_connection() as conn:
        try:
            result = epic_amend.task_split(
                conn, target["epic_id"], target["task_num"], children,
            )
        except LookupError as exc:
            return _not_found_outcome(str(exc))
        except ValueError as exc:
            return _bad_request_outcome(str(exc))
    response = SplitResponse(
        epic_id=target["epic_id"],
        parent_task_num=result.parent_task_num,
        new_task_nums=list(result.new_task_nums),
        updated_dependencies=dict(result.updated_dependencies),
    )
    return HandlerOutcome(result_payload=response.model_dump(), primary_success=True)


def handle_reassign(request: FunctionCallRequest) -> HandlerOutcome:
    """Reassign a task's worktree via ``epic_amend.task_reassign``."""
    target = _target_ids(request)
    if target is None or target["task_num"] == 0:
        return _bad_request_outcome("target must carry epic_id + task_num")
    try:
        payload = ReassignRequest.model_validate(request.payload)
    except Exception as exc:
        return _bad_request_outcome(f"payload invalid: {exc}")
    with _open_connection() as conn:
        try:
            result = epic_amend.task_reassign(
                conn, target["epic_id"], target["task_num"], payload.new_worktree,
            )
        except LookupError as exc:
            return _not_found_outcome(str(exc))
        except ValueError as exc:
            return _bad_request_outcome(str(exc))
    response = ReassignResponse(
        epic_id=target["epic_id"], task_num=result.task_num,
        old_worktree=result.old_worktree, new_worktree=result.new_worktree,
    )
    return HandlerOutcome(result_payload=response.model_dump(), primary_success=True)


def handle_add(request: FunctionCallRequest) -> HandlerOutcome:
    """Append a new task via ``epic_amend.task_add``."""
    target = _target_ids(request)
    if target is None:
        return _bad_request_outcome("target must carry epic_id")
    try:
        payload = AddRequest.model_validate(request.payload)
    except Exception as exc:
        return _bad_request_outcome(f"payload invalid: {exc}")
    with _open_connection() as conn:
        try:
            result = epic_amend.task_add(
                conn, target["epic_id"],
                title=payload.title, body=payload.body,
                worktree=payload.worktree,
                context_estimate=payload.context_estimate,
                dependencies=payload.dependencies,
            )
        except ValueError as exc:
            return _bad_request_outcome(str(exc))
    response = AddResponse(
        epic_id=target["epic_id"], task_num=result.task_num, title=result.title,
    )
    return HandlerOutcome(result_payload=response.model_dump(), primary_success=True)


def handle_remove(request: FunctionCallRequest) -> HandlerOutcome:
    """Delete a task via ``epic_amend.task_remove``."""
    target = _target_ids(request)
    if target is None or target["task_num"] == 0:
        return _bad_request_outcome("target must carry epic_id + task_num")
    try:
        payload = RemoveRequest.model_validate(request.payload)
    except Exception as exc:
        return _bad_request_outcome(f"payload invalid: {exc}")
    with _open_connection() as conn:
        try:
            result = epic_amend.task_remove(
                conn, target["epic_id"], target["task_num"], payload.reason,
            )
        except LookupError as exc:
            return _not_found_outcome(str(exc))
    response = RemoveResponse(
        epic_id=target["epic_id"], task_num=result.task_num,
        cascade_updated=dict(result.cascade_updated),
    )
    return HandlerOutcome(result_payload=response.model_dump(), primary_success=True)


def handle_metadata_update(request: FunctionCallRequest) -> HandlerOutcome:
    """Patch task metadata via ``epic_amend.task_metadata_update``."""
    target = _target_ids(request)
    if target is None or target["task_num"] == 0:
        return _bad_request_outcome("target must carry epic_id + task_num")
    try:
        payload = MetadataUpdateRequest.model_validate(request.payload)
    except Exception as exc:
        return _bad_request_outcome(f"payload invalid: {exc}")
    with _open_connection() as conn:
        try:
            result = epic_amend.task_metadata_update(
                conn, target["epic_id"], target["task_num"], payload.fields,
            )
        except LookupError as exc:
            return _not_found_outcome(str(exc))
        except ValueError as exc:
            return _bad_request_outcome(str(exc))
    response = MetadataUpdateResponse(
        epic_id=target["epic_id"], task_num=result.task_num,
        updated_fields=dict(result.updated_fields),
    )
    return HandlerOutcome(result_payload=response.model_dump(), primary_success=True)


# ---------------------------------------------------------------------------
# Registration descriptors (one entry per function id)
# ---------------------------------------------------------------------------


def _kwargs(fid: str, h: Any, req: Any, resp: Any) -> Dict[str, Any]:
    return {
        "function_id": fid, "handler": h,
        "request_model": req, "response_model": resp,
        "stability": "stable",
        "owner_module": "yoke_core.domain.handlers.workflow_item_epic_task",
        "target_kinds": ["epic_task"],
        "side_effects": ["render_body", "github_sync", "rebuild_board"],
        "emitted_event_names": ["YokeFunctionCalled"],
        "guardrails": [],
        "adapter_status": "live",
        "claim_required_kind": "epic",
    }


REGISTRATIONS: List[Dict[str, Any]] = [
    _kwargs("workflow_item.epic_task.body_replace", handle_body_replace,
            BodyReplaceRequest, BodyReplaceResponse),
    _kwargs("workflow_item.epic_task.split", handle_split,
            SplitRequest, SplitResponse),
    _kwargs("workflow_item.epic_task.reassign", handle_reassign,
            ReassignRequest, ReassignResponse),
    _kwargs("workflow_item.epic_task.add", handle_add,
            AddRequest, AddResponse),
    _kwargs("workflow_item.epic_task.remove", handle_remove,
            RemoveRequest, RemoveResponse),
    _kwargs("workflow_item.epic_task.metadata_update", handle_metadata_update,
            MetadataUpdateRequest, MetadataUpdateResponse),
]


__all__ = [
    "handle_body_replace", "handle_split", "handle_reassign",
    "handle_add", "handle_remove", "handle_metadata_update",
    "REGISTRATIONS",
]
