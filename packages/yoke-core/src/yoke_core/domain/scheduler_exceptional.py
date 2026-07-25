"""Exceptional-item reads for the shared scheduler."""

from __future__ import annotations

from typing import Any, Dict, List

from . import db_backend

FAILED_STATUS = "failed"


def query_exceptional_items(
    conn: Any,
    project_scope: List[int],
) -> List[Dict[str, Any]]:
    """Query failed items across the given project scope."""
    if not project_scope:
        return []
    placeholder = "%s" if db_backend.connection_is_postgres(conn) else "?"
    placeholders = ", ".join(placeholder for _ in project_scope)
    try:
        rows = conn.execute(
            f"""SELECT i.id, i.title, i.status, i.priority, i.project_id,
                       i.workflow_id, i.workflow_version_id,
                       v.version AS workflow_version, i.created_at
               FROM items i
               LEFT JOIN workflow_versions v ON v.id = i.workflow_version_id
               WHERE i.project_id IN ({placeholders})
                 AND i.status = {placeholder}
                 AND (i.frozen IS NULL OR i.frozen = 0)""",
            (*project_scope, FAILED_STATUS),
        ).fetchall()
        return [dict(row) for row in rows] if rows else []
    except db_backend.operational_error_types(conn):
        if db_backend.connection_is_postgres(conn):
            try:
                conn.rollback()
            except Exception:
                pass
        return []
    except IndexError:
        return []


def project_slug_or_id(conn: Any, project_id: Any) -> str:
    """Resolve a project id to its slug, falling back to raw text."""
    if project_id is None:
        return ""
    from .project_identity import resolve_project_slug

    try:
        return resolve_project_slug(conn, int(project_id))
    except Exception:
        return str(project_id)


__all__ = ["FAILED_STATUS", "project_slug_or_id", "query_exceptional_items"]
