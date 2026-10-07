"""Plain JSON-payload item sections for direct-execution records.

Evidence, escalation, and survey records are structured payloads an
engine writes and reads back whole. They need persistence and nothing
else — no body re-render, no section event — which is what separates
them from :mod:`yoke_core.domain.sections`, the operator-facing surface
behind ``items.section.upsert``.
"""

from __future__ import annotations

import json
from typing import Any, Iterable, Mapping, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.schema_common import _table_exists

SECTION_SOURCE = "direct-workflow"


def _placeholder(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def upsert_section(
    conn: Any,
    *,
    item_id: int,
    section: str,
    content: str,
    ordering: int,
) -> None:
    """Write one section's text, replacing whatever the name held."""
    marker = _placeholder(conn)
    now = iso8601_now()
    conn.execute(
        "INSERT INTO item_sections "
        "(item_id, section_name, content, ordering, source, created_at, updated_at) "
        f"VALUES ({', '.join(marker for _ in range(7))}) "
        "ON CONFLICT(item_id, section_name) DO UPDATE SET "
        "content = excluded.content, source = excluded.source, "
        "updated_at = excluded.updated_at",
        (
            int(item_id),
            section,
            content,
            ordering,
            SECTION_SOURCE,
            now,
            now,
        ),
    )


def upsert_json_section(
    conn: Any,
    *,
    item_id: int,
    section: str,
    payload: Mapping[str, Any],
    ordering: int,
) -> None:
    """Write one section as sorted, indented JSON so diffs stay readable."""
    upsert_section(
        conn,
        item_id=item_id,
        section=section,
        content=json.dumps(dict(payload), sort_keys=True, indent=2),
        ordering=ordering,
    )


def read_json_section(
    conn: Any,
    *,
    item_id: int,
    section: str,
) -> Optional[dict[str, Any]]:
    """Read one JSON-shaped item section.

    A missing table, a missing row, and unparseable content all answer
    ``None``: to every caller the record simply is not there yet.
    """
    if not _table_exists(conn, "item_sections"):
        return None
    marker = _placeholder(conn)
    row = conn.execute(
        "SELECT content FROM item_sections "
        f"WHERE item_id = {marker} AND section_name = {marker}",
        (int(item_id), section),
    ).fetchone()
    if row is None:
        return None
    return _parsed(row[0])


def read_json_sections(
    conn: Any,
    *,
    item_ids: Iterable[int],
    section: str,
) -> dict[int, dict[str, Any]]:
    """Read one JSON-shaped section for many items in a single query.

    Items whose record is missing or unparseable are absent from the result,
    exactly as :func:`read_json_section` answers ``None`` for them.
    """
    ids = sorted({int(item_id) for item_id in item_ids})
    if not ids or not _table_exists(conn, "item_sections"):
        return {}
    marker = _placeholder(conn)
    rows = conn.execute(
        "SELECT item_id, content FROM item_sections "
        f"WHERE section_name = {marker} "
        f"AND item_id IN ({', '.join(marker for _ in ids)})",
        (section, *ids),
    ).fetchall()
    parsed = {int(row[0]): _parsed(row[1]) for row in rows}
    return {item_id: record for item_id, record in parsed.items() if record}


def _parsed(content: Any) -> Optional[dict[str, Any]]:
    try:
        parsed = json.loads(str(content))
    except (TypeError, ValueError):
        return None
    return dict(parsed) if isinstance(parsed, Mapping) else None


__all__ = [
    "SECTION_SOURCE",
    "read_json_section",
    "read_json_sections",
    "upsert_json_section",
    "upsert_section",
]
