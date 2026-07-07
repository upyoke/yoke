"""Handlers for the ``items.section.*`` function family.

Three function ids:

- ``items.section.upsert`` — insert or replace an ``item_sections`` row
  via :func:`yoke_core.domain.sections.upsert_section`, then re-render
  the item body. Accepts ``target.kind="section"`` with ``item_id`` and
  ``section_name``.
- ``items.section.delete`` — drop an ``item_sections`` row via
  :func:`yoke_core.domain.sections.delete_section` and re-render.
- ``items.section.get`` — read-only fetch via
  :func:`yoke_core.domain.sections.get_section` (no mutation, no
  events).

Each handler is a thin Pydantic-shaped wrapper around the existing
``sections`` domain owner. The owner handles connection lifecycle,
``COALESCE`` ordering preservation, and source attribution. The
handler maps the typed envelope to/from that owner.

Future-concept absorption target: when the execution journal
lands, ``items.section.upsert`` / ``items.section.delete`` become
journal-emit + ``sections.*`` pairs and these handlers merge into the
journal hot path. ``items.section.get`` stays a read-only fast path.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from yoke_core.domain import sections as _sections
from yoke_core.domain.backlog_queries import VALID_STRUCTURED_FIELDS
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    FunctionWarning,
    HandlerOutcome,
)


def _github_sync_degraded_warning(step: str, detail: str) -> FunctionWarning:
    """Build the standard ``github_sync_degraded`` warning for section paths."""
    return FunctionWarning(
        code="github_sync_degraded",
        step=step,
        detail=detail,
        recovery_function="resync.fix",
    )


class UpsertRequest(BaseModel):
    content: str
    ordering: Optional[int] = None
    source: Optional[str] = None


class UpsertResponse(BaseModel):
    item_id: int
    section_name: str
    new_line_count: int
    verification: str


class DeleteRequest(BaseModel):
    pass


class DeleteResponse(BaseModel):
    item_id: int
    section_name: str
    deleted: bool


class GetRequest(BaseModel):
    pass


class GetResponse(BaseModel):
    item_id: int
    section_name: str
    found: bool
    content: str = ""
    line_count: int = 0


def _bad_request(message: str) -> HandlerOutcome:
    return HandlerOutcome(
        result_payload={}, primary_success=False,
        error=FunctionError(code="invalid_payload", message=message),
    )


def _not_found(message: str) -> HandlerOutcome:
    return HandlerOutcome(
        result_payload={}, primary_success=False,
        error=FunctionError(code="target_not_found", message=message),
    )


def _resolve_section_target(request: FunctionCallRequest):
    target = request.target
    if target.kind != "section":
        return None, _bad_request(
            "target must carry kind='section' with item_id and section_name"
        )
    if target.item_id is None:
        return None, _bad_request("target.item_id is required")
    if not target.section_name or not target.section_name.strip():
        return None, _bad_request("target.section_name is required")
    return (int(target.item_id), target.section_name), None


def _line_count(text: str) -> int:
    if not text:
        return 0
    trailing = 0 if text.endswith("\n") else 1
    return text.count("\n") + trailing


class _NullSink:
    """Discard inner-write log lines while still satisfying ``TextIO``."""

    def write(self, _data: str) -> int:  # pragma: no cover - trivial
        return 0

    def flush(self) -> None:  # pragma: no cover - trivial
        return None


def handle_upsert(request: FunctionCallRequest) -> HandlerOutcome:
    """Upsert an item_sections row + re-render body + emit SectionUpserted."""
    resolved, err = _resolve_section_target(request)
    if err is not None:
        return err
    item_id, section_name = resolved
    if section_name in VALID_STRUCTURED_FIELDS:
        return _bad_request(
            f"'{section_name}' is a structured field, not a section; "
            "use items.structured_field.replace instead",
        )
    try:
        payload = UpsertRequest.model_validate(request.payload)
    except Exception as exc:
        return _bad_request(f"payload invalid: {exc}")
    if not payload.content or not payload.content.strip():
        return HandlerOutcome(
            result_payload={}, primary_success=False,
            error=FunctionError(
                code="empty_body",
                message="refusing section upsert with empty content",
            ),
        )

    _sections.upsert_section(
        item_id=item_id,
        section_name=section_name,
        content=payload.content,
        ordering=payload.ordering,
        source=payload.source,
    )
    render_ok = _sections._rerender_body(
        item_id, "upsert", None, _NullSink(), _NullSink(),
    )
    _sections._emit_section_event("SectionUpserted", item_id, section_name)
    if not render_ok:
        return HandlerOutcome(
            result_payload={}, primary_success=False,
            error=FunctionError(
                code="render_failed",
                message="body render failed after section upsert",
            ),
        )

    sync_ok, sync_reason = _sections.sync_body_after_section_mutation(
        item_id, "upsert",
    )

    persisted = _sections.get_section(item_id, section_name) or ""
    response = UpsertResponse(
        item_id=item_id,
        section_name=section_name,
        new_line_count=_line_count(persisted),
        verification="ok" if persisted == payload.content else "drift",
    )
    warnings = (
        [_github_sync_degraded_warning("body_sync", sync_reason)]
        if not sync_ok
        else []
    )
    return HandlerOutcome(
        result_payload=response.model_dump(),
        primary_success=True,
        warnings=warnings,
    )


def handle_delete(request: FunctionCallRequest) -> HandlerOutcome:
    """Delete an item_sections row + re-render body + emit SectionDeleted."""
    resolved, err = _resolve_section_target(request)
    if err is not None:
        return err
    item_id, section_name = resolved

    existing = _sections.get_section(item_id, section_name)
    if existing is None:
        response = DeleteResponse(
            item_id=item_id, section_name=section_name, deleted=False,
        )
        return HandlerOutcome(
            result_payload=response.model_dump(),
            primary_success=True,
        )

    _sections.delete_section(item_id=item_id, section_name=section_name)
    render_ok = _sections._rerender_body(
        item_id, "delete", None, _NullSink(), _NullSink(),
    )
    _sections._emit_section_event("SectionDeleted", item_id, section_name)

    warnings: List[FunctionWarning] = []
    if render_ok:
        sync_ok, sync_reason = _sections.sync_body_after_section_mutation(
            item_id, "delete",
        )
        if not sync_ok:
            warnings.append(
                _github_sync_degraded_warning("body_sync", sync_reason),
            )

    response = DeleteResponse(
        item_id=item_id, section_name=section_name, deleted=True,
    )
    return HandlerOutcome(
        result_payload=response.model_dump(),
        primary_success=True,
        warnings=warnings,
    )


def handle_get(request: FunctionCallRequest) -> HandlerOutcome:
    """Read an item_sections row. No mutation, no event."""
    resolved, err = _resolve_section_target(request)
    if err is not None:
        return err
    item_id, section_name = resolved

    content = _sections.get_section(item_id, section_name)
    if content is None:
        return _not_found(
            f"section {section_name!r} not found on YOK-{item_id}",
        )
    response = GetResponse(
        item_id=item_id,
        section_name=section_name,
        found=True,
        content=content,
        line_count=_line_count(content),
    )
    return HandlerOutcome(
        result_payload=response.model_dump(),
        primary_success=True,
    )


_OWNER = "yoke_core.domain.handlers.items_section"


REGISTRATIONS: List[Dict[str, Any]] = [
    {
        "function_id": "items.section.upsert",
        "handler": handle_upsert,
        "request_model": UpsertRequest,
        "response_model": UpsertResponse,
        "stability": "stable",
        "owner_module": _OWNER,
        "target_kinds": ["section"],
        "side_effects": ["render_body", "github_sync", "rebuild_board"],
        "emitted_event_names": ["SectionUpserted"],
        "guardrails": ["empty_body"],
        "adapter_status": "live",
        "claim_required_kind": "item",
    },
    {
        "function_id": "items.section.delete",
        "handler": handle_delete,
        "request_model": DeleteRequest,
        "response_model": DeleteResponse,
        "stability": "stable",
        "owner_module": _OWNER,
        "target_kinds": ["section"],
        "side_effects": ["render_body", "github_sync", "rebuild_board"],
        "emitted_event_names": ["SectionDeleted"],
        "guardrails": [],
        "adapter_status": "live",
        "claim_required_kind": "item",
    },
    {
        "function_id": "items.section.get",
        "handler": handle_get,
        "request_model": GetRequest,
        "response_model": GetResponse,
        "stability": "stable",
        "owner_module": _OWNER,
        "target_kinds": ["section"],
        "side_effects": [],
        "emitted_event_names": [],
        "guardrails": [],
        "adapter_status": "live",
        "claim_required_kind": None,
    },
]


__all__ = [
    "UpsertRequest", "UpsertResponse",
    "DeleteRequest", "DeleteResponse",
    "GetRequest", "GetResponse",
    "handle_upsert", "handle_delete", "handle_get",
    "REGISTRATIONS",
]
