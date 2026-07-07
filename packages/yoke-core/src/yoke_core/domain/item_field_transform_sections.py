"""Section-level transforms for rendered item sections.

Sibling of :mod:`yoke_core.domain.item_field_transform`. ``section-upsert``
replaces an existing rendered structured-field section in-field when exactly
one match exists; otherwise it falls back to the ``item_sections`` row path.
``section-append`` appends Progress Log-style entries to ``item_sections``.
Structured-field writes route through the guarded structured-write owner, and
item-section writes route through :mod:`yoke_core.domain.sections`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Callable, Optional

from yoke_core.domain import sections as _sections
from yoke_core.domain.backlog_queries import VALID_STRUCTURED_FIELDS
from yoke_core.domain.render_body import STRUCTURED_FIELDS as _RENDERED_FIELDS
from yoke_core.domain.render_body_section import (
    has_top_level_section,
    normalise_heading,
    replace_section,
)
from yoke_core.domain.item_field_transform_sync import sync_section_body

if TYPE_CHECKING:  # pragma: no cover - type checking only
    from yoke_core.domain.item_field_transform import TransformResult


SECTION_UPSERT = "section-upsert"
SECTION_APPEND = "section-append"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class _NullSink:
    """Discard inner-write log lines while still satisfying ``TextIO``."""

    def write(self, _data: str) -> int:  # pragma: no cover - trivial
        return 0

    def flush(self) -> None:  # pragma: no cover - trivial
        return None


def _line_count(text: str) -> int:
    if not text:
        return 0
    trailing = 0 if text.endswith("\n") else 1
    return text.count("\n") + trailing


def _result(**kwargs) -> "TransformResult":
    from yoke_core.domain.item_field_transform import TransformResult
    return TransformResult(**kwargs)


def _format_entry(*, timestamp: str, headline: str, body: str) -> str:
    """Format a single Progress Log-style entry block."""
    body_clean = body.rstrip("\n")
    return f"## {timestamp} entry — {headline.strip()}\n{body_clean}\n"


def _join_entry(existing: str, entry: str) -> str:
    """Append *entry* to *existing* with at least one blank-line separator."""
    if not existing:
        return entry
    if existing.endswith("\n\n"):
        return existing + entry
    if existing.endswith("\n"):
        return existing + "\n" + entry
    return existing + "\n\n" + entry


def _read_field(item_id: int, field: str) -> Optional[str]:
    from yoke_core.domain.backlog_queries import (
        _query_item_field, _resolve_write_db_path,
    )
    from yoke_core.domain.db_helpers import connect
    conn = connect(_resolve_write_db_path())
    try:
        return _query_item_field(conn, item_id, field)
    finally:
        conn.close()


def _find_fields_with_section(
    item_id: int, heading: str,
) -> list[tuple[str, str]]:
    matches: list[tuple[str, str]] = []
    for field in _RENDERED_FIELDS:
        content_val = _read_field(item_id, field) or ""
        if has_top_level_section(content_val, heading):
            matches.append((field, content_val))
    return matches


def _section_upsert_in_field(
    *, item_id: int, section: str, heading_norm: str, field: str,
    field_content: str, new_section_content: str, source: Optional[str],
    rebuild_board: bool = True,
) -> "TransformResult":
    from yoke_core.domain.backlog_structured_write_op import (
        execute_structured_write,
    )
    base = dict(
        operation=SECTION_UPSERT, item_id=item_id, section=section, field=field,
    )
    old_lines = _line_count(field_content)
    new_field_content = replace_section(
        field_content, heading_norm, new_section_content,
    )
    if new_field_content is None:
        return _result(
            success=False,
            error=f"section '{heading_norm}' disappeared before replacement",
            verification="missing", old_line_count=old_lines, **base,
        )
    write_result = execute_structured_write(
        item_id=item_id, field=field, content=new_field_content,
        source=source or "", rebuild_board=rebuild_board, out=_NullSink(),
    )
    if not write_result.get("success"):
        err = str(write_result.get("error") or "structured write failed")
        return _result(success=False, error=err, old_line_count=old_lines, **base)
    persisted = _read_field(item_id, field) or ""
    new_lines = _line_count(persisted)
    if not has_top_level_section(persisted, heading_norm):
        return _result(
            success=False,
            error=f"post-write verification failed: heading missing in '{field}'",
            verification="missing", old_line_count=old_lines,
            new_line_count=new_lines, **base,
        )
    return _result(
        success=True, changed=True, old_line_count=old_lines,
        new_line_count=new_lines, verification="ok",
        warning=str(write_result.get("sync_warning") or ""), **base,
    )


def section_upsert(
    *,
    item_id: int,
    section: str,
    content: str,
    ordering: Optional[int] = None,
    source: Optional[str] = None,
    rebuild_board: bool = True,
) -> TransformResult:
    """Upsert a top-level ``## heading`` section.

    When exactly one structured field already contains the named
    heading, route the upsert into that field through the guarded
    structured-write path so the renderer does not emit the section
    twice. Multiple matches return a guarded failure with no write.
    No match falls through to the canonical ``item_sections`` path.
    """
    op = SECTION_UPSERT
    if not section or not section.strip():
        return _result(
            success=False, operation=op, item_id=item_id,
            error="section name is required",
        )
    if section in VALID_STRUCTURED_FIELDS:
        return _result(
            success=False, operation=op, item_id=item_id, section=section,
            error=(
                f"'{section}' is a structured field, not a section."
                " Use append-addendum or write the field directly with --stdin."
            ),
        )
    if content is None or not content.strip():
        return _result(
            success=False, operation=op, item_id=item_id, section=section,
            error="refusing section upsert with empty content",
        )

    heading_norm = normalise_heading(section)
    if heading_norm:
        matches = _find_fields_with_section(item_id, heading_norm)
        if len(matches) > 1:
            fields = ", ".join(m[0] for m in matches)
            return _result(
                success=False, operation=op, item_id=item_id, section=section,
                error=(
                    f"section '{heading_norm}' is present in multiple"
                    f" structured fields ({fields}); refusing to write"
                ),
            )
        if len(matches) == 1:
            field, field_content = matches[0]
            return _section_upsert_in_field(
                item_id=item_id, section=section, heading_norm=heading_norm,
                field=field, field_content=field_content,
                new_section_content=content, source=source,
                rebuild_board=rebuild_board,
            )

    try:
        _sections.upsert_section(
            item_id=item_id, section_name=section, content=content,
            ordering=ordering, source=source,
        )
        render_ok = _sections._rerender_body(
            item_id, "upsert", None, _NullSink(), _NullSink()
        )
        _sections._emit_section_event("SectionUpserted", item_id, section)
    except Exception as exc:  # pragma: no cover - mirrors sections owner
        return _result(
            success=False, operation=op, item_id=item_id, section=section,
            error=f"section upsert failed: {exc}",
        )
    if not render_ok:
        return _result(
            success=False, operation=op, item_id=item_id, section=section,
            error="body render failed after section upsert",
            verification="render-failed",
        )

    _sync_ok, sync_reason = _sections.sync_body_after_section_mutation(
        item_id, "upsert",
    )

    persisted = _sections.get_section(item_id, section)
    if persisted is None:
        return _result(
            success=False, operation=op, item_id=item_id, section=section,
            error="post-write verification failed: section not found",
            verification="missing",
        )
    return _result(
        success=True, operation=op, item_id=item_id, section=section,
        changed=True, new_line_count=_line_count(persisted),
        verification="ok",
        warning=sync_reason,
    )


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
    op = SECTION_APPEND
    if not section or not section.strip():
        return _result(
            success=False, operation=op, item_id=item_id,
            error="section name is required",
        )
    if section in VALID_STRUCTURED_FIELDS:
        return _result(
            success=False, operation=op, item_id=item_id, section=section,
            error=(
                f"'{section}' is a structured field, not a section."
                " Use append-addendum or write the field directly with --stdin."
            ),
        )
    if not headline or not headline.strip():
        return _result(
            success=False, operation=op, item_id=item_id, section=section,
            error="headline is required",
        )
    if content is None or not content.strip():
        return _result(
            success=False, operation=op, item_id=item_id, section=section,
            error="refusing section append with empty content",
        )

    existing = _sections.get_section(item_id, section) or ""
    old_lines = _line_count(existing)

    timestamp = (now_fn or _utc_now)().strftime("%Y-%m-%dT%H:%M:%SZ")
    headline_clean = headline.strip()
    entry = _format_entry(
        timestamp=timestamp, headline=headline_clean, body=content,
    )
    new_content = _join_entry(existing, entry)

    try:
        _sections.upsert_section(
            item_id=item_id, section_name=section, content=new_content,
            ordering=ordering, source=source,
        )
        render_ok = _sections._rerender_body(
            item_id, "append", None, _NullSink(), _NullSink()
        )
        _sections._emit_section_event("SectionAppended", item_id, section)
    except Exception as exc:  # pragma: no cover - mirrors sections owner
        return _result(
            success=False, operation=op, item_id=item_id, section=section,
            error=f"section append failed: {exc}",
            old_line_count=old_lines,
        )

    if not render_ok:
        return _result(
            success=False, operation=op, item_id=item_id, section=section,
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
            success=False, operation=op, item_id=item_id, section=section,
            error="post-write verification failed: appended entry not found",
            verification="missing",
            old_line_count=old_lines,
            new_line_count=_line_count(persisted or ""),
        )

    return _result(
        success=True, operation=op, item_id=item_id, section=section,
        changed=True, old_line_count=old_lines,
        new_line_count=_line_count(persisted),
        verification="ok",
        warning=sync_reason, body_sync_mode=sync_mode,
        body_sync_elapsed_ms=sync_ms,
    )


__all__ = [
    "SECTION_APPEND",
    "SECTION_UPSERT",
    "section_append",
    "section_upsert",
]
