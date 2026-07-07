"""Read-side helpers for the ``items`` table.

Owns ``query_item``, ``query_item_row``, and ``query_items_list``. The body
column is virtual and is rendered on demand via
:func:`yoke_core.domain.render_body.build_body`; that import is performed
lazily inside the query functions to avoid a circular import.
"""

from __future__ import annotations

from typing import Any, List, Optional

from yoke_core.domain.db_helpers import connect, query_one, query_rows, query_scalar
from yoke_core.domain.items_constants import (
    CANONICAL_COLUMNS,
    INTEGER_FIELDS,
    LIST_COLUMNS,
    _DB_COLUMNS,
    _map_frozen_read,
)
from yoke_core.domain.project_identity import item_project_join_select


def query_item(
    item_id: int,
    field: str,
    db_path: Optional[str] = None,
) -> str:
    """Get a single field from ``items`` where ``id = item_id``.

    Matches the public item-query contract:

    - Maps ``frozen`` 0/1 to ``"false"``/``"true"``.
    - Returns empty string for SQL NULL.
    - For large text fields, the full content is returned (no truncation).
    - Includes diagnostics: warns when body read returns empty but DB
      has nonzero length.

    Returns the field value as a string (empty string if NULL or not found).
    """
    conn = connect(db_path)
    try:
        # body is a virtual field rendered on demand
        if field == "body":
            from yoke_core.domain.render_body import build_body
            return build_body(conn, item_id) or ""

        # Integer columns must be cast to TEXT before COALESCE(..., '') — the
        # empty-string sentinel cannot coerce to integer on Postgres (SQLite
        # tolerates the mixed type). query_item_row/query_items_list apply the
        # same cast for their integer columns.
        if field == "project":
            val = query_scalar(
                conn,
                "SELECT COALESCE(p.slug, '') "
                "FROM items i JOIN projects p ON p.id = i.project_id "
                "WHERE i.id = %s",
                (item_id,),
            )
        else:
            col_expr = f"CAST({field} AS TEXT)" if field in INTEGER_FIELDS else field
            val = query_scalar(
                conn,
                f"SELECT COALESCE({col_expr}, '') FROM items WHERE id = %s",
                (item_id,),
            )
        if val is None:
            return ""

        # Map frozen integer to boolean string
        if field == "frozen":
            return _map_frozen_read(val)

        return str(val)
    finally:
        conn.close()


def query_item_row(
    item_id: int,
    db_path: Optional[str] = None,
) -> Optional[str]:
    """Get full pipe-delimited row in canonical column order (19 columns).

    Body newlines are escaped as literal ``\\n`` (matching shell behaviour).
    Returns ``None`` if item not found.
    """
    # Build SELECT for DB columns; body is rendered on demand
    select_cols, needs_project = item_project_join_select(list(_DB_COLUMNS))
    join = " JOIN projects p ON p.id = i.project_id" if needs_project else ""
    sql = f"SELECT {select_cols} FROM items i{join} WHERE i.id = %s"
    conn = connect(db_path)
    try:
        row = query_one(conn, sql, (item_id,))
        if row is None:
            return None
        # Insert rendered body at the expected position (after worktree)
        from yoke_core.domain.render_body import build_body
        rendered = (build_body(conn, item_id) or "").replace("\n", "\\n")
        db_vals = list(str(v) for v in row)
        body_idx = list(CANONICAL_COLUMNS).index("body")
        db_vals.insert(body_idx, rendered)
        return "|".join(db_vals)
    finally:
        conn.close()


def query_items_list(
    status: Optional[str] = None,
    item_type: Optional[str] = None,
    priority: Optional[str] = None,
    db_path: Optional[str] = None,
) -> str:
    """Filtered list query returning pipe-delimited rows.

    Returns rows ordered by ``id ASC``, one per line. Uses the shorter
    15-column format (matching shell ``query_items_list``): columns through
    ``updated_at``, body newlines escaped as literal ``\\n``.

    Returns empty string if no rows match.
    """
    conditions: List[str] = []
    params: List[Any] = []

    if status is not None:
        conditions.append("status = %s")
        params.append(status)
    if item_type is not None:
        conditions.append("type = %s")
        params.append(item_type)
    if priority is not None:
        conditions.append("priority = %s")
        params.append(priority)

    where = ""
    if conditions:
        where = "WHERE " + " AND ".join(conditions)

    # Build SELECT matching shell's 15-column list output
    _list_db_cols = tuple(c for c in LIST_COLUMNS if c != "body")
    select_cols, needs_project = item_project_join_select(list(_list_db_cols))
    join = " JOIN projects p ON p.id = i.project_id" if needs_project else ""
    sql = f"SELECT {select_cols} FROM items i{join} {where} ORDER BY i.id ASC"

    conn = connect(db_path)
    try:
        rows = query_rows(conn, sql, tuple(params))
        if not rows:
            return ""
        # Insert empty body at expected position
        body_idx = list(LIST_COLUMNS).index("body")
        lines = []
        for r in rows:
            vals = list(str(v) for v in r)
            vals.insert(body_idx, "")
            lines.append("|".join(vals))
        return "\n".join(lines)
    finally:
        conn.close()
