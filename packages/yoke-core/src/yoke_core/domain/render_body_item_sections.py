"""Render stored ``item_sections`` rows into the virtual item body.

NULL ``ordering`` uses the same unset sentinel as ``sections.list_sections``
so a write that omitted ``--ordering`` still appears in ``items.body``.

The two groups partition every ordering there is rather than covering a
window of them. A section below the boundary renders early and one at or
above it renders late, so a stored row is always in exactly one group. Any
gap at either end would be a section that exists in the database, accepts
its write without complaint, and then appears nowhere in the body.
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


def fetch_item_sections(conn: Any, item_id: int, *, late: bool) -> list[Any]:
    """Return one side of the boundary, ordered as stored.

    ``late`` selects the comparison rather than a range, which is what keeps
    the two groups exhaustive: every ordering is either below the boundary
    or not. The comparison operator comes from a boolean here, never from
    caller data.
    """
    p = _p(conn)
    comparison = ">=" if late else "<"
    return query_rows(
        conn,
        f"""
        SELECT section_name, content
        FROM item_sections
        WHERE item_id = {p}
          AND COALESCE(ordering, {p}) {comparison} {p}
        ORDER BY COALESCE(ordering, {p}), section_name
        """,
        (
            item_id,
            UNSET_ITEM_SECTION_ORDERING,
            EARLY_ITEM_SECTION_ORDERING_LIMIT,
            UNSET_ITEM_SECTION_ORDERING,
        ),
    )


def append_item_sections(
    chunks: list[str], conn: Any, item_id: int, *, late: bool,
) -> None:
    if not _schema_table_exists(conn, "item_sections"):
        return
    for sec_row in fetch_item_sections(conn, item_id, late=late):
        content = sec_row["content"]
        if _section_has_content(content):
            chunks.append(
                _render_section(f"## {sec_row['section_name']}", str(content))
            )


def append_early_item_sections(
    chunks: list[str], conn: Any, item_id: int,
) -> None:
    append_item_sections(chunks, conn, item_id, late=False)


def append_late_item_sections(
    chunks: list[str], conn: Any, item_id: int,
) -> None:
    append_item_sections(chunks, conn, item_id, late=True)


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
