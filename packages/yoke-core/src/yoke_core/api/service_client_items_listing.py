"""Items listing/active-queue/count command handlers.

Owns the SELECT-many commands that render filtered lists of items: the
active-queue (non-done/cancelled/frozen) feed, the generic ``item-list``
with field selection, and ``item-count`` for filter-driven counting.
"""

from __future__ import annotations

import sys

from yoke_core.api.service_client_shared import (
    _get_db_readonly,
    queries,
)
from yoke_core.api.service_client_items_parsing import (
    _QI_VIRTUAL_FIELDS,
    _parse_item_filters,
    _validate_fields,
)
from yoke_core.domain.project_identity import item_project_join_select


def cmd_active_queue(args: list[str]) -> int:
    """List active queue items (non-done, non-cancelled, non-frozen).

    Usage: active-queue [--project P] [--fields "f1,f2,..."]

    Delegates frozen/lifecycle/exclusion semantics to the domain layer.
    Output: pipe-delimited rows, one per item, with requested fields.
    Default fields: id|title|status|priority|type|project
    """
    project = None
    fields = "id,title,status,priority,type,project"

    i = 0
    while i < len(args):
        if args[i] == "--project" and i + 1 < len(args):
            project = args[i + 1]
            i += 2
        elif args[i] == "--fields" and i + 1 < len(args):
            fields = args[i + 1]
            i += 2
        else:
            print(f"Unknown argument: {args[i]}", file=sys.stderr)
            return 2

    # Build filter via domain layer
    item_filter = queries.active_queue_filter(project=project)
    where_clause, params = queries.build_where_clause(item_filter, table_prefix="i.")

    # Build SELECT with requested fields
    field_list = [f.strip() for f in fields.split(",")]
    select_cols, needs_project = item_project_join_select(field_list)
    join = " JOIN projects p ON p.id = i.project_id" if needs_project else ""
    sql = f"SELECT {select_cols} FROM items i{join} {where_clause} ORDER BY i.id"

    conn = _get_db_readonly()
    try:
        rows = conn.execute(sql, params).fetchall()
        for row in rows:
            print("|".join(str(v) for v in row))
        return 0
    finally:
        conn.close()


def cmd_item_list(args: list[str]) -> int:
    """List items with optional filters.

    Usage: item-list [--status S] [--priority S] [--type S] [--frozen 0|1]
                     [--project P] [--fields "f1,f2,..."] [--limit N]

    Output: pipe-delimited rows, one per line.
    Default fields: id,title,status,priority,type,source
    Exit 0 on results, 1 on empty.
    """
    parsed = _parse_item_filters(args, allow_limit=True)
    if isinstance(parsed, int):
        return parsed
    filt, fields_csv, limit = parsed

    field_list = _validate_fields(fields_csv)
    if field_list is None:
        return 2

    # Separate DB columns from virtual fields
    db_fields = [f for f in field_list if f not in _QI_VIRTUAL_FIELDS]
    virtual_positions = {i: f for i, f in enumerate(field_list) if f in _QI_VIRTUAL_FIELDS}
    needs_hidden_id = bool(virtual_positions) and "id" not in db_fields

    where_clause, params = queries.build_where_clause(filt, table_prefix="i.")
    if db_fields:
        select_cols, needs_project = item_project_join_select(db_fields)
        if needs_hidden_id:
            select_cols = f"i.id AS __item_id, {select_cols}"
    else:
        needs_project = False
        select_cols = "i.id AS __item_id" if needs_hidden_id else "i.id"
    join = " JOIN projects p ON p.id = i.project_id" if needs_project else ""
    sql = f"SELECT {select_cols} FROM items i{join} {where_clause} ORDER BY i.id"
    sql_params: tuple = tuple(params)
    if limit is not None:
        sql += " LIMIT %s"
        sql_params = (*sql_params, limit)

    conn = _get_db_readonly()
    try:
        rows = conn.execute(sql, sql_params).fetchall()
        if not rows:
            return 1
        if not virtual_positions:
            for row in rows:
                print("|".join(str(v) for v in row))
        else:
            from yoke_core.domain.render_body import build_body
            for row in rows:
                db_vals = list(str(v) for v in row)
                if needs_hidden_id:
                    item_id = row["__item_id"]
                    db_vals = db_vals[1:]
                else:
                    item_id = row["id"]
                # Reconstruct full output with virtual fields inserted
                out_vals: list[str] = []
                db_idx = 0
                for i in range(len(field_list)):
                    if i in virtual_positions:
                        if virtual_positions[i] == "body":
                            out_vals.append(build_body(conn, int(item_id)) or "")
                        else:
                            out_vals.append("")
                    else:
                        out_vals.append(db_vals[db_idx])
                        db_idx += 1
                print("|".join(out_vals))
        return 0
    finally:
        conn.close()


def cmd_item_count(args: list[str]) -> int:
    """Count items with optional filters.

    Usage: item-count [--status S] [--priority S] [--type S] [--frozen 0|1]
                      [--project P]

    Output: single integer.
    Exit 0 if count > 0, exit 1 if count == 0.
    """
    parsed = _parse_item_filters(args)
    if isinstance(parsed, int):
        return parsed
    filt, _, _ = parsed

    where_clause, params = queries.build_where_clause(filt)
    conn = _get_db_readonly()
    try:
        row = conn.execute(
            f"SELECT COUNT(*) AS item_count FROM items {where_clause}",
            params,
        ).fetchone()
        count = row["item_count"] if row else 0
        print(count)
        return 0 if count > 0 else 1
    finally:
        conn.close()


__all__ = [
    "cmd_active_queue",
    "cmd_item_list",
    "cmd_item_count",
]
