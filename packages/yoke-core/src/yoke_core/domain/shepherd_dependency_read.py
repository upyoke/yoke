"""Read-side projection for shepherd dependency rows.

Split from :mod:`yoke_core.domain.shepherd_dependency` (the writes) so
each file stays under the authored-file line cap. ``dependency_rows`` is
the single owner of the both-direction projection; the
``shepherd dependency-list`` CLI and the ``shepherd.dependency_list.run``
function handler both consume it.
"""
from __future__ import annotations

from typing import List

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.shepherd_records import normalize_item_id


# Result names for the dependency-list projection, in SELECT order.
DEPENDENCY_LIST_COLUMNS = (
    "direction", "other_item", "gate_point", "satisfaction", "source",
    "session_id", "created_at", "rationale", "evidence_summary",
)


def _placeholder(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def dependency_rows(conn, item: str) -> List[dict]:
    """Typed both-direction dependency rows for one item ref.

    ``direction='depends-on'`` rows name the blocker this item waits on;
    ``direction='blocks'`` rows name the dependent waiting on this item
    (directional edges — the blocker side never waits).
    """
    item = normalize_item_id(item)
    p = _placeholder(conn)
    rows = query_rows(
        conn,
        "SELECT 'depends-on' AS direction, blocking_item AS other_item, "
        "gate_point, satisfaction, source, COALESCE(CAST(session_id AS TEXT), ''), "
        "created_at, rationale, "
        "CASE WHEN evidence_json IS NULL OR evidence_json='' OR evidence_json='{}' "
        "THEN '' ELSE evidence_json END AS evidence_summary "
        f"FROM item_dependencies WHERE dependent_item={p} "
        "UNION ALL "
        "SELECT 'blocks' AS direction, dependent_item AS other_item, "
        "gate_point, satisfaction, source, COALESCE(CAST(session_id AS TEXT), ''), "
        "created_at, rationale, "
        "CASE WHEN evidence_json IS NULL OR evidence_json='' OR evidence_json='{}' "
        "THEN '' ELSE evidence_json END AS evidence_summary "
        f"FROM item_dependencies WHERE blocking_item={p} "
        "ORDER BY created_at",
        (item, item),
    )
    return [
        {
            name: ("" if value is None else str(value))
            for name, value in zip(DEPENDENCY_LIST_COLUMNS, tuple(row))
        }
        for row in rows
    ]


def cmd_dependency_list(conn, item: str) -> str:
    """Pipe-row rendering of :func:`dependency_rows` for the CLI."""
    return "\n".join(
        "|".join(row[name] for name in DEPENDENCY_LIST_COLUMNS)
        for row in dependency_rows(conn, item)
    )


__all__ = [
    "DEPENDENCY_LIST_COLUMNS",
    "cmd_dependency_list",
    "dependency_rows",
]
