"""Handler for ``ouroboros.field_note.append``.

Records one agent-authored field-note signal — "this recipe failed when
I ran it", "I needed a recipe that didn't exist", "a recipe was present
but its purpose was unclear", or "I noticed something worth logging"
(observation kind). The signal is persisted by:

1. Writing one row to ``ouroboros_entries`` via ``cmd_insert_entry`` —
   this is the AUTHORITATIVE store. ``/yoke curate`` reads this table.
2. Emitting one ``OuroborosFieldNoteAppended`` event for telemetry. The
   event is best-effort: if event emission fails AFTER the durable row
   is written, the call still reports ``primary_success=True`` with
   ``event_id=None`` (the durable store is authoritative).

If the durable write fails (``cmd_insert_entry`` raises), the call
reports ``primary_success=False`` with ``error.code="emit_failed"`` and
NO event is emitted (no use logging telemetry for a write that did not
land).

Attribution is resolved at write time, not left for a later pass: the
row records a meaningful author label from the calling session and a
project slug that prefers a client checkout hint over the session's
project scope (see ``ouroboros_field_note_provenance``). A note that
supersedes an earlier one passes ``corrects`` and the two are linked
rather than left sitting next to each other in the unreviewed queue
(see ``ouroboros_entry_corrections``).

Target shape: ``target.kind = "global"`` (no item, claim, or project
binding). The dispatcher's claim-verification matrix treats ``global``
as "no claim required". Checkout project rides on the payload, not the
target — the server never resolves an ambient cwd.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from yoke_core.domain import events as _events
from yoke_core.domain.db_helpers import connect, iso8601_now
from yoke_core.domain.ouroboros_entries import cmd_insert_entry
from yoke_core.domain.ouroboros_entry_corrections import (
    CorrectionTargetError,
    record_correction,
)
from yoke_core.domain.ouroboros_field_note_provenance import resolve_provenance
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_contracts.field_note_text import (
    CATEGORY_PREFIX,
    EVIDENCE_MAX_CHARS,
    KIND_VALUES,
)


FIELD_NOTE_EVENT_NAME = "OuroborosFieldNoteAppended"
FIELD_NOTE_KIND_VALUES = KIND_VALUES
EVIDENCE_PREVIEW_CHARS = 120


class FieldNoteAppendRequest(BaseModel):
    kind: Literal["failed", "new", "unclear", "observation"]
    evidence: str = Field(..., min_length=1, max_length=EVIDENCE_MAX_CHARS)
    correlation_id: Optional[str] = None
    # Dispatched subagent role, when the caller runs as one. Attribution
    # falls back to the session's executor.
    actor_role: Optional[str] = None
    # Client-resolved registered checkout project (slug or numeric id).
    # Wins over the session's project scope when present; omitted when the
    # caller has no checkout mapping (global/no-checkout fallback).
    project: Optional[str] = None
    # Entry id this note corrects; that note is superseded, not duplicated.
    corrects: Optional[int] = None


class FieldNoteAppendResponse(BaseModel):
    event_id: Optional[str]
    entry_id: Optional[str]
    kind: str
    evidence_preview: str
    correlation_id: Optional[str]
    author: str
    project: Optional[str]
    corrects: Optional[int]
    github_sync: str
    body_sync_mode: str
    body_sync_elapsed_ms: int


def _bad_request(message: str) -> HandlerOutcome:
    return HandlerOutcome(
        result_payload={},
        primary_success=False,
        error=FunctionError(code="invalid_payload", message=message),
    )


def _emit_failed(reason: str) -> HandlerOutcome:
    return HandlerOutcome(
        result_payload={},
        primary_success=False,
        error=FunctionError(code="emit_failed", message=reason),
    )


def handle_append(request: FunctionCallRequest) -> HandlerOutcome:
    """Persist one field-note: durable row first, telemetry event second."""
    target = request.target
    if target.kind != "global":
        return _bad_request("target.kind must be 'global'")

    try:
        payload = FieldNoteAppendRequest.model_validate(request.payload)
    except Exception as exc:
        return _bad_request(f"payload invalid: {exc}")

    evidence_preview = payload.evidence[:EVIDENCE_PREVIEW_CHARS]
    timestamp = iso8601_now()
    category = f"{CATEGORY_PREFIX}{payload.kind}"
    session_id = request.actor.session_id

    # Durable write FIRST. If it raises, surface emit_failed and skip the event.
    # Provenance, the row, and any supersede link land on one connection so a
    # correction is never recorded against a note that failed to write.
    try:
        with connect() as conn:
            provenance = resolve_provenance(
                conn,
                actor_role=payload.actor_role,
                session_id=session_id,
                project=payload.project,
            )
            entry_id = cmd_insert_entry(
                conn,
                timestamp,
                provenance.author,
                None,  # context — reserved, unused by field-note channel
                category,
                payload.evidence,
                project=provenance.project,
            )
            if payload.corrects is not None and entry_id.isdigit():
                record_correction(
                    conn,
                    correction_entry_id=int(entry_id),
                    corrected_entry_id=payload.corrects,
                )
    except CorrectionTargetError as exc:
        return _bad_request(str(exc))
    except LookupError as exc:
        # Unknown checkout project hint — refuse rather than silently
        # attributing to the session project (isolation).
        return _bad_request(str(exc))
    except Exception as exc:
        return _emit_failed(f"durable write failed: {exc}")

    linked_correction = (
        payload.corrects
        if payload.corrects is not None and entry_id.isdigit()
        else None
    )

    context: Dict[str, Any] = {
        "kind": payload.kind,
        "evidence": payload.evidence,
        "entry_id": entry_id,
        "author": provenance.author,
    }
    if provenance.project:
        context["project"] = provenance.project
    if linked_correction is not None:
        context["corrects"] = linked_correction
    if payload.correlation_id:
        context["correlation_id"] = payload.correlation_id

    # Telemetry SECOND. Failure here does NOT roll back the durable row —
    # the row is authoritative; the event is best-effort.
    result = _events.emit_event(
        FIELD_NOTE_EVENT_NAME,
        event_kind="domain",
        event_type="ouroboros_feedback",
        source_type="agent",
        session_id=session_id or "",
        severity="INFO",
        outcome="completed",
        context=context,
    )

    response = FieldNoteAppendResponse(
        event_id=result.event_id if result.ok else None,
        entry_id=entry_id,
        kind=payload.kind,
        evidence_preview=evidence_preview,
        correlation_id=payload.correlation_id,
        author=provenance.author,
        project=provenance.project,
        corrects=linked_correction,
        github_sync="not_applicable",
        body_sync_mode="not_applicable",
        body_sync_elapsed_ms=0,
    )
    return HandlerOutcome(
        result_payload=response.model_dump(),
        primary_success=True,
    )


REGISTRATIONS: List[Dict[str, Any]] = [
    {
        "function_id": "ouroboros.field_note.append",
        "handler": handle_append,
        "request_model": FieldNoteAppendRequest,
        "response_model": FieldNoteAppendResponse,
        "stability": "stable",
        "owner_module": "yoke_core.domain.handlers.ouroboros_field_note",
        "target_kinds": ["global"],
        "side_effects": ["db_write", "event_emit"],
        "emitted_event_names": [FIELD_NOTE_EVENT_NAME],
        "guardrails": ["evidence_required"],
        "adapter_status": "live",
        "claim_required_kind": None,
        "ambient_session_required": False,
    },
]


__all__ = [
    "EVIDENCE_MAX_CHARS",
    "EVIDENCE_PREVIEW_CHARS",
    "FIELD_NOTE_EVENT_NAME",
    "FIELD_NOTE_KIND_VALUES",
    "FieldNoteAppendRequest",
    "FieldNoteAppendResponse",
    "REGISTRATIONS",
    "handle_append",
]
