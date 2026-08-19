"""Render stored ``item_sections`` rows into the virtual item body.

NULL ``ordering`` uses the same unset sentinel as ``sections.list_sections``
so a write that omitted ``--ordering`` still appears in ``items.body``.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import connect, query_rows
from yoke_core.domain.render_body_section import (
    extract_section,
    render_section_block as _render_section,
    section_has_content as _section_has_content,
)
from yoke_core.domain.schema_common import _table_exists as _schema_table_exists


UNSET_ITEM_SECTION_ORDERING = 999999
EARLY_ITEM_SECTION_ORDERING_LIMIT = 500


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def fetch_item_sections(
    conn: Any,
    item_id: int,
    *,
    min_ordering: int,
    max_ordering: int,
) -> list[Any]:
    p = _p(conn)
    unset = UNSET_ITEM_SECTION_ORDERING
    return query_rows(
        conn,
        f"""
        SELECT section_name, content
        FROM item_sections
        WHERE item_id = {p}
          AND COALESCE(ordering, {p}) >= {p}
          AND COALESCE(ordering, {p}) < {p}
        ORDER BY COALESCE(ordering, {p}), section_name
        """,
        (item_id, unset, min_ordering, unset, max_ordering, unset),
    )


def append_item_sections(
    chunks: list[str], conn: Any, item_id: int,
    *, min_ordering: int, max_ordering: int,
) -> None:
    if not _schema_table_exists(conn, "item_sections"):
        return
    for sec_row in fetch_item_sections(
        conn, item_id, min_ordering=min_ordering, max_ordering=max_ordering,
    ):
        content = sec_row["content"]
        if _section_has_content(content):
            chunks.append(
                _render_section(f"## {sec_row['section_name']}", str(content))
            )


def append_early_item_sections(
    chunks: list[str], conn: Any, item_id: int,
) -> None:
    append_item_sections(
        chunks, conn, item_id,
        min_ordering=0, max_ordering=EARLY_ITEM_SECTION_ORDERING_LIMIT,
    )


def append_late_item_sections(
    chunks: list[str], conn: Any, item_id: int,
) -> None:
    append_item_sections(
        chunks, conn, item_id,
        min_ordering=EARLY_ITEM_SECTION_ORDERING_LIMIT,
        max_ordering=UNSET_ITEM_SECTION_ORDERING + 1,
    )


def section_visible_in_rendered_body(
    item_id: int,
    section: str,
    *,
    db_path: Optional[str] = None,
) -> bool:
    """Return True iff ``## section`` is present in the live rendered body."""
    from yoke_core.domain.render_body import build_body
    conn = connect(db_path)
    try:
        body = build_body(conn, item_id)
    finally:
        conn.close()
    return bool(body) and extract_section(body, section) is not None
