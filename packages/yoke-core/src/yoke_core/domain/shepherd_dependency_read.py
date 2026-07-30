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
from yoke_core.domain.item_ref_columns import (
    column_item_id_sql,
    resolve_column_item_ref,
)
from yoke_core.domain.shepherd_records import normalize_item_id


# Result names for the dependency-list projection, in SELECT order.
DEPENDENCY_LIST_COLUMNS = (
    "direction", "other_item", "gate_point", "satisfaction", "source",
    "session_id", "created_at", "rationale", "evidence_summary",
)

# Direction reported for an edge whose counterpart ref names no item at all.
# Surfacing it keeps a dangling edge visible to the party that can still be
# resolved instead of dropping it out of both sides' listings.
UNRESOLVED_DIRECTION = "unresolved-ref"

_PROJECTION = (
    "gate_point, satisfaction, source, COALESCE(CAST(session_id AS TEXT), ''), "
    "created_at, rationale, "
    "CASE WHEN evidence_json IS NULL OR evidence_json='' OR evidence_json='{}' "
    "THEN '' ELSE evidence_json END AS evidence_summary"
)


def _placeholder(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _side_select(
    conn, *, direction: str, other_column: str, own_column: str,
) -> str:
    """One UNION branch: this item's edges in one direction.

    Matches on the ref resolved through prefix + project sequence, with the
    raw stored text as a second chance so a row written before the columns
    held true public refs still lists. The trailing ``other_item_id``
    column is internal — ``NULL`` marks a counterpart that names no item.
    """
    p = _placeholder(conn)
    own_id_sql = column_item_id_sql(conn, own_column)
    other_id_sql = column_item_id_sql(conn, other_column)
    return (
        f"SELECT '{direction}' AS direction, {other_column} AS other_item, "
        + _PROJECTION
        + f", {other_id_sql} AS other_item_id "
        f"FROM item_dependencies "
        f"WHERE {own_id_sql} = {p} OR {own_column} = {p}"
    )


def dependency_rows(conn, item: str) -> List[dict]:
    """Typed both-direction dependency rows for one item ref.

    ``direction='depends-on'`` rows name the blocker this item waits on;
    ``direction='blocks'`` rows name the dependent waiting on this item
    (directional edges — the blocker side never waits). A row whose
    counterpart ref resolves to no item is reported with
    ``direction='unresolved-ref'`` and its raw stored text as
    ``other_item``.
    """
    ref = normalize_item_id(item, conn)
    item_id = resolve_column_item_ref(conn, ref)
    rows = query_rows(
        conn,
        _side_select(
            conn,
            direction="depends-on",
            other_column="blocking_item",
            own_column="dependent_item",
        )
        + " UNION ALL "
        + _side_select(
            conn,
            direction="blocks",
            other_column="dependent_item",
            own_column="blocking_item",
        )
        + " ORDER BY created_at",
        (item_id, ref, item_id, ref),
    )
    projected: List[dict] = []
    for row in rows:
        values = tuple(row)
        record = {
            name: ("" if value is None else str(value))
            for name, value in zip(DEPENDENCY_LIST_COLUMNS, values)
        }
        if values[len(DEPENDENCY_LIST_COLUMNS)] is None:
            record["direction"] = UNRESOLVED_DIRECTION
        projected.append(record)
    return projected


def cmd_dependency_list(conn, item: str) -> str:
    """Pipe-row rendering of :func:`dependency_rows` for the CLI."""
    return "\n".join(
        "|".join(row[name] for name in DEPENDENCY_LIST_COLUMNS)
        for row in dependency_rows(conn, item)
    )


__all__ = [
    "DEPENDENCY_LIST_COLUMNS",
    "UNRESOLVED_DIRECTION",
    "cmd_dependency_list",
    "dependency_rows",
]
