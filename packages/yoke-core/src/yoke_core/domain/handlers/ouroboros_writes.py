"""Ouroboros entry/write lifecycle handlers."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_contracts.field_note_text import CATEGORY_PREFIX
from yoke_core.domain.ouroboros_entry_review import MAX_ENTRY_REVIEW_BATCH


class OuroborosEntryInsertRequest(BaseModel):
    agent: str
    category: str
    observation: str
    context: Optional[str] = None
    timestamp: Optional[str] = None
    project: Optional[str] = None


class OuroborosEntryInsertResponse(BaseModel):
    entry_id: str


class OuroborosEntryReviewRequest(BaseModel):
    entry_id: Optional[int] = None
    before: Optional[str] = None
    field_notes_before: Optional[str] = None
    limit: int = Field(
        default=MAX_ENTRY_REVIEW_BATCH,
        ge=1,
        le=MAX_ENTRY_REVIEW_BATCH,
    )


class OuroborosEntryReviewResponse(BaseModel):
    message: str
    reviewed_count: int
    remaining_count: Optional[int] = None


class OuroborosEntryLifecycleResponse(BaseModel):
    message: str


class OuroborosEntryArchiveRequest(BaseModel):
    entry_id: Optional[int] = None
    all_reviewed: bool = False
    # Optional project slug/id. Required for --all-reviewed over https
    # (authz resolves it); single-id archive may omit and use the entry row.
    project: Optional[str] = None


def _bad_request(message: str, *, jsonpath: str = "$.payload") -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(
            code="payload_invalid",
            message=message,
            jsonpath=jsonpath,
        ),
    )


def handle_ouroboros_entry_insert(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    try:
        payload = OuroborosEntryInsertRequest.model_validate(request.payload or {})
    except Exception as exc:
        return _bad_request(f"payload invalid: {exc}")
    if not payload.agent.strip():
        return _bad_request("agent must be non-empty", jsonpath="$.payload.agent")
    if not payload.category.strip():
        return _bad_request("category must be non-empty", jsonpath="$.payload.category")
    if not payload.observation.strip():
        return _bad_request(
            "observation must be non-empty", jsonpath="$.payload.observation"
        )
    from yoke_core.domain.db_helpers import connect, iso8601_now
    from yoke_core.domain.ouroboros_entries import cmd_insert_entry

    with connect() as conn:
        entry_id = cmd_insert_entry(
            conn,
            payload.timestamp or iso8601_now(),
            payload.agent,
            payload.context,
            payload.category,
            payload.observation,
            payload.project,
        )
    return HandlerOutcome(
        result_payload=OuroborosEntryInsertResponse(
            entry_id=entry_id,
        ).model_dump(),
        primary_success=True,
    )


def handle_ouroboros_entry_mark_reviewed(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    try:
        payload = OuroborosEntryReviewRequest.model_validate(request.payload or {})
    except Exception as exc:
        return _bad_request(f"payload invalid: {exc}")
    selectors = (payload.entry_id, payload.before, payload.field_notes_before)
    if sum(selector is not None for selector in selectors) != 1:
        return _bad_request(
            "pass exactly one of entry_id, before, or field_notes_before"
        )
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.ouroboros_entries import cmd_mark_reviewed
    from yoke_core.domain.ouroboros_entry_review import (
        mark_entries_reviewed_before,
    )

    try:
        with connect() as conn:
            if payload.entry_id is not None:
                message = cmd_mark_reviewed(conn, payload.entry_id)
                result = OuroborosEntryReviewResponse(
                    message=message,
                    reviewed_count=1,
                )
            else:
                cutoff = payload.before or payload.field_notes_before or ""
                field_notes_only = payload.field_notes_before is not None
                batch = mark_entries_reviewed_before(
                    conn,
                    before=cutoff,
                    category_prefix=CATEGORY_PREFIX if field_notes_only else None,
                    limit=payload.limit,
                )
                subject = "field-notes" if field_notes_only else "entries"
                message = (
                    f"Marked {batch.reviewed_count} {subject} created before "
                    f"{cutoff} as reviewed"
                )
                if batch.reviewed_at:
                    message += f" at {batch.reviewed_at}"
                message += f"; {batch.remaining_count} remain"
                result = OuroborosEntryReviewResponse(
                    message=message,
                    reviewed_count=batch.reviewed_count,
                    remaining_count=batch.remaining_count,
                )
    except LookupError as exc:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(code="not_found", message=str(exc)),
        )
    except ValueError as exc:
        return _bad_request(str(exc))
    return HandlerOutcome(
        result_payload=result.model_dump(),
        primary_success=True,
    )


def handle_ouroboros_entry_mark_archived(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    try:
        payload = OuroborosEntryArchiveRequest.model_validate(request.payload or {})
    except Exception as exc:
        return _bad_request(f"payload invalid: {exc}")
    if not payload.all_reviewed and payload.entry_id is None:
        return _bad_request("entry_id is required unless all_reviewed=true")
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.ouroboros_entries import cmd_mark_archived

    try:
        with connect() as conn:
            message = cmd_mark_archived(
                conn,
                entry_id=payload.entry_id,
                all_reviewed=payload.all_reviewed,
                project=payload.project,
            )
    except LookupError as exc:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(code="not_found", message=str(exc)),
        )
    except ValueError as exc:
        return _bad_request(str(exc))
    return HandlerOutcome(
        result_payload=OuroborosEntryLifecycleResponse(
            message=message,
        ).model_dump(),
        primary_success=True,
    )


REGISTRATIONS: List[Dict[str, Any]] = [
    {
        "function_id": "ouroboros.entry.insert",
        "handler": handle_ouroboros_entry_insert,
        "request_model": OuroborosEntryInsertRequest,
        "response_model": OuroborosEntryInsertResponse,
        "side_effects": ["db_write"],
    },
    {
        "function_id": "ouroboros.entry.mark_reviewed",
        "handler": handle_ouroboros_entry_mark_reviewed,
        "request_model": OuroborosEntryReviewRequest,
        "response_model": OuroborosEntryReviewResponse,
        "side_effects": ["db_write"],
    },
    {
        "function_id": "ouroboros.entry.mark_archived",
        "handler": handle_ouroboros_entry_mark_archived,
        "request_model": OuroborosEntryArchiveRequest,
        "response_model": OuroborosEntryLifecycleResponse,
        "side_effects": ["db_write"],
    },
]

for entry in REGISTRATIONS:
    entry.update(
        {
            "stability": "stable",
            "owner_module": "yoke_core.domain.handlers.ouroboros_writes",
            "target_kinds": ["global"],
            "emitted_event_names": ["YokeFunctionCalled"],
            "guardrails": [],
            "adapter_status": "live",
            "claim_required_kind": None,
            "ambient_session_required": False,
        }
    )


__all__ = [
    "REGISTRATIONS",
    "handle_ouroboros_entry_insert",
    "handle_ouroboros_entry_mark_reviewed",
    "handle_ouroboros_entry_mark_archived",
]
