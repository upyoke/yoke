"""Handler for ``items.progress_log.append``.

Appends a Progress-Log-style timestamped entry to the canonical
``Progress Log`` section on an item, following the convention documented
in AGENTS.md ``## Progress Log``:

- Section name is exactly ``"Progress Log"`` (case-sensitive, two words).
- ``ordering=200`` keeps the section after the standard structured
  fields and before any operator-authored sections that have no
  explicit ordering.
- Each entry leads with an ISO-8601 UTC timestamp + a short headline
  via :func:`yoke_core.domain.item_field_transform.section_append`.

This handler is the read-then-upsert-with-ordering=200 wrapper. It is
intentionally NOT a parallel append API in the sections domain owner —
the canonical surface is :func:`item_field_transform.section_append`,
and this handler just pins the section name + ordering for callers
that want to write to the Progress Log specifically.

Future-concept absorption target: when the execution journal lands,
``items.progress_log.append`` becomes a journal-emit + section
projection pair and this handler merges into the journal hot path.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from yoke_core.domain import item_field_transform
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    FunctionWarning,
    HandlerOutcome,
)


PROGRESS_LOG_SECTION = "Progress Log"
PROGRESS_LOG_ORDERING = 200


class AppendRequest(BaseModel):
    headline: str
    content: str
    source: Optional[str] = None


class AppendResponse(BaseModel):
    item_id: int
    section: str
    changed: bool
    old_line_count: int
    new_line_count: int
    verification: str
    github_sync: str
    body_sync_mode: str
    body_sync_elapsed_ms: int


def _bad_request(message: str) -> HandlerOutcome:
    return HandlerOutcome(
        result_payload={}, primary_success=False,
        error=FunctionError(code="invalid_payload", message=message),
    )


def handle_append(request: FunctionCallRequest) -> HandlerOutcome:
    """Append one entry to the ``Progress Log`` section on the target item."""
    target = request.target
    if target.kind != "item" or target.item_id is None:
        return _bad_request("target must carry kind='item' and item_id")
    try:
        payload = AppendRequest.model_validate(request.payload)
    except Exception as exc:
        return _bad_request(f"payload invalid: {exc}")

    item_id = int(target.item_id)
    result = item_field_transform.section_append(
        item_id=item_id,
        section=PROGRESS_LOG_SECTION,
        headline=payload.headline,
        content=payload.content,
        ordering=PROGRESS_LOG_ORDERING,
        source=payload.source,
    )
    if not result.success:
        return HandlerOutcome(
            result_payload={}, primary_success=False,
            error=FunctionError(
                code="write_failed",
                message=result.error or "progress_log append failed",
            ),
        )

    response = AppendResponse(
        item_id=item_id,
        section=PROGRESS_LOG_SECTION,
        changed=result.changed,
        old_line_count=result.old_line_count,
        new_line_count=result.new_line_count,
        verification=result.verification,
        github_sync="degraded" if result.warning else "ok",
        body_sync_mode=result.body_sync_mode or "unknown",
        body_sync_elapsed_ms=result.body_sync_elapsed_ms,
    )
    return HandlerOutcome(
        result_payload=response.model_dump(),
        primary_success=True,
        warnings=[
            FunctionWarning(
                code="github_sync_degraded",
                step="github_sync",
                detail=result.warning,
            )
        ] if result.warning else [],
    )


REGISTRATIONS: List[Dict[str, Any]] = [
    {
        "function_id": "items.progress_log.append",
        "handler": handle_append,
        "request_model": AppendRequest,
        "response_model": AppendResponse,
        "stability": "stable",
        "owner_module": "yoke_core.domain.handlers.items_progress_log",
        "target_kinds": ["item"],
        "side_effects": ["render_body", "github_sync", "rebuild_board"],
        "emitted_event_names": ["SectionAppended"],
        "guardrails": ["empty_body"],
        "adapter_status": "live",
        "claim_required_kind": "item",
    },
]


__all__ = [
    "AppendRequest", "AppendResponse",
    "handle_append",
    "PROGRESS_LOG_SECTION", "PROGRESS_LOG_ORDERING",
    "REGISTRATIONS",
]
