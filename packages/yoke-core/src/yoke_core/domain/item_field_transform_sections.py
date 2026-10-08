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
from typing import TYPE_CHECKING, Optional

from yoke_core.domain.item_json_sections import section_write_refusal
from yoke_core.domain.item_field_transform_field_section import _section_upsert_in_field
from yoke_core.domain import sections as _sections
from yoke_core.domain.backlog_queries import VALID_STRUCTURED_FIELDS
from yoke_core.domain.render_body import STRUCTURED_FIELDS as _RENDERED_FIELDS
from yoke_core.domain.render_body_item_sections import (
    section_visible_in_rendered_body,
)
from yoke_core.domain.render_body_section import (
    has_top_level_section,
    normalise_heading,
)
from yoke_core.domain.item_field_transform_sync import (
    sync_section_body as sync_section_body,
)
from yoke_core.domain.item_field_transform_section_append import section_append

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


def _read_field(item_id: int, field: str) -> Optional[str]:
    from yoke_core.domain.backlog_queries import (
        _query_item_field,
        _resolve_write_db_path,
    )
    from yoke_core.domain.db_helpers import connect

    conn = connect(_resolve_write_db_path())
    try:
        return _query_item_field(conn, item_id, field)
    finally:
        conn.close()


def _find_fields_with_section(
    item_id: int,
    heading: str,
) -> list[tuple[str, str]]:
    matches: list[tuple[str, str]] = []
    for field in _RENDERED_FIELDS:
        content_val = _read_field(item_id, field) or ""
        if has_top_level_section(content_val, heading):
            matches.append((field, content_val))
    return matches


def section_upsert(
    *,
    item_id: int,
    section: str,
    content: str,
    ordering: Optional[int] = None,
    source: Optional[str] = None,
) -> TransformResult:
    """Upsert a top-level ``## heading`` section.

    When exactly one structured field already contains the named
    heading, route the upsert into that field through the guarded
    structured-write path so the renderer does not emit the section
    twice. Multiple matches return a guarded failure with no write.
    No match falls through to the canonical ``item_sections`` path.
    """
    op = SECTION_UPSERT
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
    if content is None or not content.strip():
        return _result(
            success=False,
            operation=op,
            item_id=item_id,
            section=section,
            error="refusing section upsert with empty content",
        )

    heading_norm = normalise_heading(section)
    if heading_norm:
        matches = _find_fields_with_section(item_id, heading_norm)
        if len(matches) > 1:
            fields = ", ".join(m[0] for m in matches)
            return _result(
                success=False,
                operation=op,
                item_id=item_id,
                section=section,
                error=(
                    f"section '{heading_norm}' is present in multiple"
                    f" structured fields ({fields}); refusing to write"
                ),
            )
        if len(matches) == 1:
            field, field_content = matches[0]
            return _section_upsert_in_field(
                item_id=item_id,
                section=section,
                heading_norm=heading_norm,
                field=field,
                field_content=field_content,
                new_section_content=content,
                source=source,
            )

    try:
        _sections.upsert_section(
            item_id=item_id,
            section_name=section,
            content=content,
            ordering=ordering,
            source=source,
        )
        render_ok = _sections._rerender_body(
            item_id, "upsert", None, _NullSink(), _NullSink()
        )
        _sections._emit_section_event("SectionUpserted", item_id, section)
    except Exception as exc:  # pragma: no cover - mirrors sections owner
        return _result(
            success=False,
            operation=op,
            item_id=item_id,
            section=section,
            error=f"section upsert failed: {exc}",
        )
    if not render_ok:
        return _result(
            success=False,
            operation=op,
            item_id=item_id,
            section=section,
            error="body render failed after section upsert",
            verification="render-failed",
        )

    _sync_ok, sync_reason = _sections.sync_body_after_section_mutation(
        item_id,
        "upsert",
    )

    persisted = _sections.get_section(item_id, section)
    if persisted is None:
        return _result(
            success=False,
            operation=op,
            item_id=item_id,
            section=section,
            error="post-write verification failed: section not found",
            verification="missing",
        )
    if not section_visible_in_rendered_body(item_id, section):
        return _result(
            success=False,
            operation=op,
            item_id=item_id,
            section=section,
            error=(
                "post-write verification failed: section not reachable from a body read"
            ),
            verification="unreadable",
            new_line_count=_line_count(persisted),
        )
    return _result(
        success=True,
        operation=op,
        item_id=item_id,
        section=section,
        changed=True,
        new_line_count=_line_count(persisted),
        verification="ok",
        warning=sync_reason,
    )


__all__ = [
    "SECTION_APPEND",
    "SECTION_UPSERT",
    "section_append",
    "section_upsert",
]
