"""Handler for ``workflow_item.epic_progress_note.append``.

Appends a new ``epic_progress_notes`` row via the existing
:func:`yoke_core.domain.epic.progress_note_insert` surface. The
handler is a thin Pydantic-shaped wrapper:

- ``target.kind="epic_task"`` with both ``epic_id`` and ``task_num``.
- Payload carries ``note_num`` (1-based monotonic per task), ``body``
  (Markdown), and optional ``commit_hash`` to bind the note to a
  specific commit. Auto-numbering (``note_num=None``) is intentionally
  out of scope for v0 — operators pass a concrete number after a
  one-shot read of ``MAX(note_num) + 1``.

Future-concept absorption target: when an execution journal lands,
``epic_progress_notes`` becomes a journal projection and this handler
merges into the journal hot path.
"""

from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel, Field

from yoke_core.domain import epic
from yoke_core.domain.epic_parsing import _placeholder
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class AppendRequest(BaseModel):
    """Request payload — the dispatcher hands this through unchanged."""

    note_num: int = Field(..., ge=1)
    body: str
    commit_hash: str = ""


class AppendResponse(BaseModel):
    """Response payload echoed in ``HandlerOutcome.result_payload``."""

    epic_id: int
    task_num: int
    note_num: int


class ListRequest(BaseModel):
    """Optional list payload."""

    limit: int = Field(0, ge=0)


class ListResponse(BaseModel):
    """Pipe-delimited progress-note listing."""

    epic_id: int
    task_num: int
    body: str


def _not_found(message: str) -> HandlerOutcome:
    return HandlerOutcome(
        result_payload={}, primary_success=False,
        error=FunctionError(code="target_not_found", message=message),
    )


def _bad_request(message: str) -> HandlerOutcome:
    return HandlerOutcome(
        result_payload={}, primary_success=False,
        error=FunctionError(code="invalid_payload", message=message),
    )


def _open_connection():
    from yoke_core.domain import db_helpers
    return db_helpers.connect()


def handle_append(request: FunctionCallRequest) -> HandlerOutcome:
    """Insert one progress note row via ``epic.progress_note_insert``."""
    target = request.target
    if target.kind != "epic_task" or target.epic_id is None:
        return _bad_request("target must carry epic_id + task_num")
    if target.task_num is None:
        return _bad_request("target must carry task_num for progress-note append")
    try:
        payload = AppendRequest.model_validate(request.payload)
    except Exception as exc:
        return _bad_request(f"payload invalid: {exc}")
    epic_id = int(target.epic_id)
    task_num = int(target.task_num)
    epic_key = str(epic_id)
    with _open_connection() as conn:
        p = _placeholder(conn)
        existing = conn.execute(
            f"SELECT 1 FROM epic_tasks WHERE epic_id = {p} AND task_num = {p}",
            (epic_key, task_num),
        ).fetchone()
        if existing is None:
            return _not_found(f"epic_task {epic_key}/{task_num} not found")
        try:
            epic.progress_note_insert(
                conn, epic_key, task_num, payload.note_num,
                payload.body, payload.commit_hash,
            )
        except LookupError as exc:
            return _not_found(str(exc))
    response = AppendResponse(
        epic_id=epic_id, task_num=task_num, note_num=payload.note_num,
    )
    return HandlerOutcome(
        result_payload=response.model_dump(), primary_success=True,
    )


def handle_list(request: FunctionCallRequest) -> HandlerOutcome:
    """List progress notes for one epic task via ``epic.progress_note_list``."""
    target = request.target
    if target.kind != "epic_task" or target.epic_id is None:
        return _bad_request("target must carry epic_id + task_num")
    if target.task_num is None:
        return _bad_request("target must carry task_num for progress-note list")
    try:
        payload = ListRequest.model_validate(request.payload)
    except Exception as exc:
        return _bad_request(f"payload invalid: {exc}")
    epic_id = int(target.epic_id)
    task_num = int(target.task_num)
    epic_key = str(epic_id)
    with _open_connection() as conn:
        p = _placeholder(conn)
        existing = conn.execute(
            f"SELECT 1 FROM epic_tasks WHERE epic_id = {p} AND task_num = {p}",
            (epic_key, task_num),
        ).fetchone()
        if existing is None:
            return _not_found(f"epic_task {epic_key}/{task_num} not found")
        body = epic.progress_note_list(
            conn, epic_key, task_num, limit=payload.limit,
        )
    response = ListResponse(epic_id=epic_id, task_num=task_num, body=body)
    return HandlerOutcome(
        result_payload=response.model_dump(), primary_success=True,
    )


REGISTRATIONS: List[Dict[str, Any]] = [
    {
        "function_id": "workflow_item.epic_progress_note.append",
        "handler": handle_append,
        "request_model": AppendRequest,
        "response_model": AppendResponse,
        "stability": "stable",
        "owner_module": "yoke_core.domain.handlers.workflow_item_epic_progress_note",
        "target_kinds": ["epic_task"],
        "side_effects": ["render_body", "github_sync"],
        "emitted_event_names": ["YokeFunctionCalled"],
        "guardrails": [],
        "adapter_status": "live",
        "claim_required_kind": "epic",
    },
    {
        "function_id": "workflow_item.epic_progress_note.list",
        "handler": handle_list,
        "request_model": ListRequest,
        "response_model": ListResponse,
        "stability": "stable",
        "owner_module": "yoke_core.domain.handlers.workflow_item_epic_progress_note",
        "target_kinds": ["epic_task"],
        "side_effects": [],
        "emitted_event_names": ["YokeFunctionCalled"],
        "guardrails": [],
        "adapter_status": "live",
        "claim_required_kind": None,
    },
]


__all__ = [
    "handle_append",
    "handle_list",
    "AppendRequest",
    "AppendResponse",
    "ListRequest",
    "ListResponse",
    "REGISTRATIONS",
]
