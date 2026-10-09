"""Append timestamped entries through the guarded item-section owner."""

from __future__ import annotations

from datetime import datetime
from yoke_contracts.timestamps import format_instant
from typing import Callable, Optional, TYPE_CHECKING
from yoke_core.domain.backlog_queries import VALID_STRUCTURED_FIELDS
from yoke_core.domain.item_json_sections import section_write_refusal
from yoke_core.domain.progress_log import format_entry, join_entry

if TYPE_CHECKING:
    from yoke_core.domain.item_field_transform import TransformResult


def section_append(
    *,
    item_id: int,
    section: str,
    headline: str,
    content: str,
    ordering: Optional[int] = None,
    source: Optional[str] = None,
    now_fn: Optional[Callable[[], datetime]] = None,
) -> TransformResult:
    """Append a Progress Log-style entry to an ``item_sections`` row.

    Creates the section when missing. Appends after existing content when
    present, preserving prior bytes and using a blank-line separator. The
    entry body is assembled in Python from a UTC ISO timestamp, the
    supplied headline, and the supplied body.
    """
    from yoke_core.domain.item_field_transform_sections import (
        SECTION_APPEND,
        _result,
        _line_count,
        _sections,
        _NullSink,
        _utc_now,
        sync_section_body,
    )

    op = SECTION_APPEND
    refusal = section_write_refusal(section)
    if refusal:
        return _result(
            success=False, operation=op, item_id=item_id, section=section, error=refusal
        )
    if not section or not section.strip():
        return _result(
            success=False,
            operation=op,
            item_id=item_id,
            error="section name is required",
        )
    if section in VALID_STRUCTURED_FIELDS:
        return _result(
            success=False,
            operation=op,
            item_id=item_id,
            section=section,
            error=(
                f"'{section}' is a structured field, not a section."
                " Use append-addendum or write the field directly with --stdin."
            ),
        )
    if not headline or not headline.strip():
        return _result(
            success=False,
            operation=op,
            item_id=item_id,
            section=section,
            error="headline is required",
        )
    if content is None or not content.strip():
        return _result(
            success=False,
            operation=op,
            item_id=item_id,
            section=section,
            error="refusing section append with empty content",
        )

    existing = _sections.get_section(item_id, section) or ""
    old_lines = _line_count(existing)

    timestamp = format_instant((now_fn or _utc_now)())
    headline_clean = headline.strip()
    entry = format_entry(
        timestamp=timestamp,
        headline=headline_clean,
        body=content,
    )
    new_content = join_entry(existing, entry)

    try:
        _sections.upsert_section(
            item_id=item_id,
            section_name=section,
            content=new_content,
            ordering=ordering,
            source=source,
        )
        render_ok = _sections._rerender_body(
            item_id, "append", None, _NullSink(), _NullSink()
        )
        _sections._emit_section_event("SectionAppended", item_id, section)
    except Exception as exc:  # pragma: no cover - mirrors sections owner
        return _result(
            success=False,
            operation=op,
            item_id=item_id,
            section=section,
            error=f"section append failed: {exc}",
            old_line_count=old_lines,
        )

    if not render_ok:
        return _result(
            success=False,
            operation=op,
            item_id=item_id,
            section=section,
            error="body render failed after section append",
            verification="render-failed",
            old_line_count=old_lines,
        )

    _sync_ok, sync_reason, sync_mode, sync_ms = sync_section_body(item_id, "append")

    persisted = _sections.get_section(item_id, section)
    if (
        persisted is None
        or headline_clean not in persisted
        or content.rstrip("\n") not in persisted
    ):
        return _result(
            success=False,
            operation=op,
            item_id=item_id,
            section=section,
            error="post-write verification failed: appended entry not found",
            verification="missing",
            old_line_count=old_lines,
            new_line_count=_line_count(persisted or ""),
        )

    return _result(
        success=True,
        operation=op,
        item_id=item_id,
        section=section,
        changed=True,
        old_line_count=old_lines,
        new_line_count=_line_count(persisted),
        verification="ok",
        warning=sync_reason,
        body_sync_mode=sync_mode,
        body_sync_elapsed_ms=sync_ms,
    )
