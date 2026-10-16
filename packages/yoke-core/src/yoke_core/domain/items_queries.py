"""Read-side helpers for the ``items`` table.

Owns ``query_item``, ``query_item_row``, and ``query_items_list``. The body
column is virtual and is rendered on demand via
:func:`yoke_core.domain.render_body.build_body`; that import is performed
lazily inside the query functions to avoid a circular import.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, List, Optional

from yoke_core.domain import db_backend

from yoke_core.domain.db_helpers import connect, query_one, query_rows, query_scalar
from yoke_core.domain.items_constants import (
    CANONICAL_COLUMNS,
    LIST_COLUMNS,
    _DB_COLUMNS,
    _map_frozen_read,
)
from yoke_core.domain.project_identity import item_project_join_select
from yoke_core.domain.items_projection import item_text_expression


_FIELD_BATCH = ContextVar("item_field_read_batch", default=None)


def _text_value(field, value):
    if value is None:
        return ""
    return _map_frozen_read(value) if field == "frozen" else str(value)


@contextmanager
def item_field_read_batch(conn, item_ids, fields):
    """Read scalar fields together; each handler still owns its full validation."""
    if not db_backend.pg_dsn_is_bound():
        raise ValueError("item field batch requires an explicitly bound copy authority")
    from yoke_contracts.merge_queue_status import (
        LABEL_ATTEMPT_JOIN,
        LABEL_ENQUEUED_AT_SQL,
        LABEL_LANDED_AT_SQL,
        render_merge_queue_status,
    )

    columns = tuple(
        dict.fromkeys(
            field
            for field in fields
            if field not in {"id", "deployment_flow", "body", "merge_queue_status"}
        )
    )
    expressions = [
        "COALESCE(p.slug, '')"
        if field == "project"
        else item_text_expression(field, column=f"i.{field}")
        for field in columns
    ]
    rows = conn.execute(
        "SELECT "
        + ", ".join(
            [
                "i.id",
                *expressions,
                "i.status",
                LABEL_ENQUEUED_AT_SQL,
                LABEL_LANDED_AT_SQL,
            ]
        )
        + " "
        f"FROM items i JOIN projects p ON p.id=i.project_id {LABEL_ATTEMPT_JOIN} "
        "WHERE i.id = ANY(%s)",
        (list(item_ids),),
    ).fetchall()
    values = {}
    for row in rows:
        item_id = int(row[0])
        for index, field in enumerate(columns, 1):
            values[item_id, field] = _text_value(field, row[index])
        if "merge_queue_status" in fields:
            values[item_id, "merge_queue_status"] = render_merge_queue_status(
                row[len(columns) + 2],
                row[len(columns) + 3],
                item_status=row[len(columns) + 1],
            )
    token = _FIELD_BATCH.set((db_backend.resolve_pg_dsn(), values))
    try:
        yield
    finally:
        _FIELD_BATCH.reset(token)


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
    batch = _FIELD_BATCH.get()
    if (
        batch is not None
        and db_path is None
        and db_backend.pg_dsn_is_bound()
        and batch[0] == db_backend.resolve_pg_dsn()
        and (item_id, field) in batch[1]
    ):
        return batch[1][item_id, field]
    conn = connect(db_path)
    try:
        # body is a virtual field rendered on demand
        if field == "body":
            from yoke_core.domain.render_body import build_body

            return build_body(conn, item_id) or ""
        if field == "merge_queue_status":
            from yoke_contracts.merge_queue_status import (
                LABEL_INPUTS_FOR_ITEM_SQL,
                render_merge_queue_status,
            )

            row = query_one(
                conn,
                LABEL_INPUTS_FOR_ITEM_SQL,
                (item_id,),
            )
            return (
                render_merge_queue_status(row[1], row[2], item_status=row[0])
                if row is not None
                else ""
            )

        # This API owns a text value, including UTC clock text and empty null cells.
        if field == "project":
            val = query_scalar(
                conn,
                "SELECT COALESCE(p.slug, '') "
                "FROM items i JOIN projects p ON p.id = i.project_id "
                "WHERE i.id = %s",
                (item_id,),
            )
        else:
            val = query_scalar(
                conn,
                f"SELECT {item_text_expression(field)} FROM items WHERE id = %s",
                (item_id,),
            )
        return _text_value(field, val)
    finally:
        conn.close()


def query_item_row(
    item_id: int,
    db_path: Optional[str] = None,
) -> Optional[str]:
    """Get full pipe-delimited row in canonical column order (22 columns).

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
        # Insert rendered body at its public row-contract position.
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
    workflow: Optional[str] = None,
    priority: Optional[str] = None,
    db_path: Optional[str] = None,
) -> str:
    """Filtered list query returning pipe-delimited rows.

    Returns rows ordered by ``id ASC``, one per line. Uses the shorter
    16-column format: columns through
    ``updated_at``, body newlines escaped as literal ``\\n``.

    Returns empty string if no rows match.
    """
    conditions: List[str] = []
    params: List[Any] = []

    if status is not None:
        conditions.append("status = %s")
        params.append(status)
    if workflow is not None:
        conditions.append("workflow_id = %s")
        params.append(workflow)
    if priority is not None:
        conditions.append("priority = %s")
        params.append(priority)

    where = ""
    if conditions:
        where = "WHERE " + " AND ".join(conditions)

    # Build SELECT matching the public 16-column list output.
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
