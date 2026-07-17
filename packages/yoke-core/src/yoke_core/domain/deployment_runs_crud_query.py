"""Read-side CRUD helpers for deployment runs.

Owns: ``cmd_get``, ``cmd_list``, ``cmd_items``, ``cmd_find_by_item``.
No mutation. No state-machine logic. Imports row-shape primitives from
``deployment_runs_schema``.
"""

from __future__ import annotations

from typing import List, Optional

from yoke_core.domain.db_helpers import connect, query_one, query_rows, query_scalar
from yoke_core.domain.deployment_runs_schema import (
    RUN_FIELDS,
    _RUN_SELECT,
    _pipe_row,
    _pipe_rows,
)
from yoke_core.domain.project_identity import resolve_project_id


DEFAULT_RUN_LIST_LIMIT = 20
MAX_RUN_LIST_LIMIT = 1000


def cmd_get(
    run_id: str,
    field: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Optional[str]:
    """Get a run. Returns pipe-delimited row or single field value.

    Returns None if the run is not found (caller should handle error output).
    """
    conn = connect(db_path)
    try:
        if field:
            if field not in RUN_FIELDS:
                raise ValueError(f"invalid field '{field}'")
            exists = query_scalar(
                conn, "SELECT COUNT(*) FROM deployment_runs WHERE id=%s", (run_id,)
            )
            if not exists:
                return None
            if field == "project":
                val = query_scalar(
                    conn,
                    "SELECT COALESCE(p.slug, '') FROM deployment_runs dr "
                    "JOIN projects p ON p.id = dr.project_id "
                    "WHERE dr.id=%s",
                    (run_id,),
                )
            else:
                val = query_scalar(
                    conn, f"SELECT {field} FROM deployment_runs WHERE id=%s", (run_id,)
                )
            return str(val or "")
        else:
            row = query_one(
                conn,
                f"SELECT {_RUN_SELECT} FROM deployment_runs WHERE id=%s",
                (run_id,),
            )
            if row is None:
                return None
            return _pipe_row(row)
    finally:
        conn.close()


def cmd_list(
    project: Optional[str] = None,
    status: Optional[str] = None,
    limit: Optional[int] = None,
    db_path: Optional[str] = None,
) -> str:
    """List the most recent runs (pipe-delimited)."""
    resolved_limit = DEFAULT_RUN_LIST_LIMIT if limit is None else limit
    if (
        isinstance(resolved_limit, bool)
        or not isinstance(resolved_limit, int)
        or resolved_limit < 1
        or resolved_limit > MAX_RUN_LIST_LIMIT
    ):
        raise ValueError(
            f"limit must be an integer from 1 to {MAX_RUN_LIST_LIMIT}"
        )
    conn = connect(db_path)
    try:
        clauses: List[str] = []
        params: List[object] = []
        if project:
            clauses.append("project_id=%s")
            params.append(resolve_project_id(conn, project))
        if status:
            clauses.append("status=%s")
            params.append(status)

        where = ""
        if clauses:
            where = "WHERE " + " AND ".join(clauses)

        rows = query_rows(
            conn,
            f"SELECT {_RUN_SELECT} FROM deployment_runs {where} "
            "ORDER BY created_at DESC, id DESC LIMIT %s",
            (*params, resolved_limit),
        )
        return _pipe_rows(rows)
    finally:
        conn.close()


def cmd_items(run_id: str, db_path: Optional[str] = None) -> str:
    """List items in a run (pipe-delimited)."""
    conn = connect(db_path)
    try:
        rows = query_rows(
            conn,
            "SELECT run_id, item_id, added_at FROM deployment_run_items WHERE run_id=%s ORDER BY item_id ASC",
            (run_id,),
        )
        return _pipe_rows(rows)
    finally:
        conn.close()


def cmd_find_by_item(
    item_id: int,
    status: Optional[str] = None,
    db_path: Optional[str] = None,
) -> str:
    """Find deployment run(s) for an item. Returns pipe-delimited rows."""
    conn = connect(db_path)
    try:
        status_clause = ""
        params: list = [item_id]
        if status:
            status_clause = "AND dr.status=%s"
            params.append(status)

        rows = query_rows(
            conn,
            f"SELECT dr.id, dr.status, COALESCE(dr.current_stage,''), dr.created_at "
            f"FROM deployment_runs dr "
            f"JOIN deployment_run_items dri ON dri.run_id = dr.id "
            f"WHERE dri.item_id=%s {status_clause} "
            f"ORDER BY dr.created_at DESC",
            tuple(params),
        )
        return _pipe_rows(rows)
    finally:
        conn.close()
