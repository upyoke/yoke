"""Handlers for the ``items.structured_field.*`` function family.

Implements four function ids (replace, append_addendum, section_upsert,
section_append). Each handler is a thin wrapper: payload validation ->
domain call -> typed :class:`HandlerOutcome`. The domain owners
(:func:`backlog_structured_write_op.execute_structured_write`,
:func:`item_field_transform.append_addendum`,
:func:`item_field_transform.section_upsert`,
:func:`item_field_transform.section_append`) own all existing guards
(empty-overwrite, shrinkage, freeze, JSON-shape).

Pydantic boundary models and ``REGISTRATIONS`` live in the sibling
:mod:`items_structured_field_models` module to keep this file under
the 350-line authored-file budget.

Future-concept absorption target: when the execution journal
lands, ``items.structured_field.*`` calls become journal-emit +
domain-helper pairs and these handlers merge into the journal hot path.
"""

from __future__ import annotations

import hashlib
from typing import List, Optional

from yoke_core.domain import item_field_transform
from yoke_core.domain.backlog_queries import (
    VALID_STRUCTURED_FIELDS,
    _query_item_field,
    _resolve_write_db_path,
)
from yoke_core.domain.backlog_structured_write_op import execute_structured_write
from yoke_core.domain.db_helpers import connect
from yoke_core.domain.handlers.items_structured_field_models import (
    AppendAddendumRequest, AppendAddendumResponse,
    ReplaceRequest, ReplaceResponse,
    SectionAppendRequest, SectionAppendResponse,
    SectionUpsertRequest, SectionUpsertResponse,
)
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    FunctionWarning,
    HandlerOutcome,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _line_count(text: str) -> int:
    if not text:
        return 0
    trailing = 0 if text.endswith("\n") else 1
    return text.count("\n") + trailing


def _bad_request(message: str) -> HandlerOutcome:
    return HandlerOutcome(
        result_payload={}, primary_success=False,
        error=FunctionError(code="invalid_payload", message=message),
    )


def _empty_body(message: str) -> HandlerOutcome:
    return HandlerOutcome(
        result_payload={}, primary_success=False,
        error=FunctionError(code="empty_body", message=message),
    )


def _guard_failed(code: str, message: str) -> HandlerOutcome:
    return HandlerOutcome(
        result_payload={}, primary_success=False,
        error=FunctionError(code=code, message=message),
    )


def _require_item_target(request: FunctionCallRequest) -> Optional[int]:
    if request.target.kind != "item":
        return None
    if request.target.item_id is None:
        return None
    return int(request.target.item_id)


def _read_field(item_id: int, field: str) -> str:
    db_path = _resolve_write_db_path()
    conn = connect(db_path)
    try:
        return _query_item_field(conn, item_id, field) or ""
    finally:
        conn.close()


def _classify_write_error(error: str) -> str:
    """Map an :func:`execute_structured_write` error string to an error code."""
    lowered = (error or "").lower()
    if "invalid structured field" in lowered:
        return "invalid_field"
    if "refusing to overwrite non-empty" in lowered:
        return "empty_body"
    if "refusing" in lowered and "empty content" in lowered:
        return "empty_body"
    if "less than 50% of existing" in lowered or "shrinkage" in lowered:
        return "shrinkage"
    if "frozen" in lowered or "freeze" in lowered:
        return "freeze_lock"
    if "validation failed" in lowered:
        return "validation_failed"
    return "write_failed"


class _NullSink:
    """Discard inner-write log lines while still satisfying ``TextIO``."""

    def write(self, _data: str) -> int:  # pragma: no cover - trivial
        return 0

    def flush(self) -> None:  # pragma: no cover - trivial
        return None


def _github_sync_warnings(warning: str) -> List[FunctionWarning]:
    if not warning:
        return []
    return [FunctionWarning(
        code="github_sync_degraded",
        step="github_sync",
        detail=warning,
    )]


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def handle_replace(request: FunctionCallRequest) -> HandlerOutcome:
    """Replace a structured field via :func:`execute_structured_write`."""
    item_id = _require_item_target(request)
    if item_id is None:
        return _bad_request("target must carry kind='item' and item_id")
    try:
        payload = ReplaceRequest.model_validate(request.payload)
    except Exception as exc:
        return _bad_request(f"payload invalid: {exc}")
    if payload.field not in VALID_STRUCTURED_FIELDS:
        return _guard_failed(
            "invalid_field",
            f"invalid structured field: {payload.field!r}",
        )

    # Empty content is rejected even when the existing field is empty
    # unless preconditions.allow_empty=true AND an explicit reason is set.
    allow_empty = bool(request.preconditions.get("allow_empty"))
    reason = str(request.preconditions.get("allow_empty_reason") or "")
    has_content = bool(payload.content and payload.content.strip())
    if not has_content and not (allow_empty and reason):
        return _empty_body(
            f"refusing to write empty content for YOK-{item_id} {payload.field!r} "
            "without preconditions.allow_empty=true and an explicit reason"
        )

    existing = _read_field(item_id, payload.field)
    old_lines = _line_count(existing)
    old_hash = _hash(existing)

    result = execute_structured_write(
        item_id=item_id,
        field=payload.field,
        content=payload.content,
        source=payload.source,
        force=payload.force,
        rebuild_board=False,
        out=_NullSink(),
    )
    if not result.get("success"):
        err = str(result.get("error") or "structured write failed")
        return _guard_failed(_classify_write_error(err), err)

    persisted = _read_field(item_id, payload.field)
    new_lines = _line_count(persisted)
    new_hash = _hash(persisted)
    payload_bytes = len((payload.content or "").encode("utf-8"))

    sync_warning = str(result.get("sync_warning") or "")
    github_sync = "degraded" if sync_warning else "ok"

    response = ReplaceResponse(
        item_id=item_id,
        field=payload.field,
        old_line_count=old_lines,
        new_line_count=new_lines,
        old_hash=old_hash,
        new_hash=new_hash,
        payload_byte_count=payload_bytes,
        empty_payload=not has_content,
        verification="ok" if new_hash == _hash(payload.content) else "drift",
        github_sync=github_sync,
    )
    return HandlerOutcome(
        result_payload=response.model_dump(),
        primary_success=True,
        warnings=_github_sync_warnings(sync_warning),
    )


def handle_append_addendum(request: FunctionCallRequest) -> HandlerOutcome:
    """Append a ``## heading``-led block via ``item_field_transform.append_addendum``."""
    item_id = _require_item_target(request)
    if item_id is None:
        return _bad_request("target must carry kind='item' and item_id")
    try:
        payload = AppendAddendumRequest.model_validate(request.payload)
    except Exception as exc:
        return _bad_request(f"payload invalid: {exc}")

    result = item_field_transform.append_addendum(
        item_id=item_id,
        field=payload.field,
        heading=payload.heading,
        content=payload.content,
        source=payload.source,
        rebuild_board=False,
    )
    if not result.success:
        return _guard_failed(
            _classify_write_error(result.error),
            result.error or "append_addendum failed",
        )

    response = AppendAddendumResponse(
        item_id=item_id,
        field=payload.field,
        heading=payload.heading,
        changed=result.changed,
        old_line_count=result.old_line_count,
        new_line_count=result.new_line_count,
        verification=result.verification,
    )
    return HandlerOutcome(
        result_payload=response.model_dump(),
        primary_success=True,
        warnings=_github_sync_warnings(result.warning),
    )


def handle_section_upsert(request: FunctionCallRequest) -> HandlerOutcome:
    """Upsert a rendered section via ``item_field_transform.section_upsert``."""
    item_id = _require_item_target(request)
    if item_id is None:
        return _bad_request("target must carry kind='item' and item_id")
    try:
        payload = SectionUpsertRequest.model_validate(request.payload)
    except Exception as exc:
        return _bad_request(f"payload invalid: {exc}")

    result = item_field_transform.section_upsert(
        item_id=item_id,
        section=payload.section,
        content=payload.content,
        ordering=payload.ordering,
        source=payload.source,
        rebuild_board=False,
    )
    if not result.success:
        return _guard_failed(
            _classify_write_error(result.error),
            result.error or "section_upsert failed",
        )

    response = SectionUpsertResponse(
        item_id=item_id,
        section=payload.section,
        changed=result.changed,
        new_line_count=result.new_line_count,
        verification=result.verification,
    )
    return HandlerOutcome(
        result_payload=response.model_dump(),
        primary_success=True,
        warnings=_github_sync_warnings(result.warning),
    )


def handle_section_append(request: FunctionCallRequest) -> HandlerOutcome:
    """Append a timestamped entry via ``item_field_transform.section_append``."""
    item_id = _require_item_target(request)
    if item_id is None:
        return _bad_request("target must carry kind='item' and item_id")
    try:
        payload = SectionAppendRequest.model_validate(request.payload)
    except Exception as exc:
        return _bad_request(f"payload invalid: {exc}")

    result = item_field_transform.section_append(
        item_id=item_id,
        section=payload.section,
        headline=payload.headline,
        content=payload.content,
        ordering=payload.ordering,
        source=payload.source,
    )
    if not result.success:
        return _guard_failed(
            _classify_write_error(result.error),
            result.error or "section_append failed",
        )

    response = SectionAppendResponse(
        item_id=item_id,
        section=payload.section,
        changed=result.changed,
        old_line_count=result.old_line_count,
        new_line_count=result.new_line_count,
        verification=result.verification,
    )
    return HandlerOutcome(
        result_payload=response.model_dump(),
        primary_success=True,
        warnings=_github_sync_warnings(result.warning),
    )


# Registry binding metadata lives in the sibling models module — this
# module exposes the handler callables and the models module composes
# them into ``REGISTRATIONS`` for ``register_all_handlers``.


__all__ = [
    "handle_replace", "handle_append_addendum",
    "handle_section_upsert", "handle_section_append",
]
