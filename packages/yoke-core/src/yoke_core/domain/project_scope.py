"""Project-scope normalization for scheduler/frontier readers."""

from __future__ import annotations

from typing import Any, List

from yoke_core.domain import db_backend
from yoke_core.domain.project_identity import resolve_project_id


def normalize_project_scope(conn: Any, project_scope: List[Any]) -> List[int]:
    """Resolve mixed slug/id scope input into numeric ``projects.id`` values.

    Every slug must resolve against the ``projects`` table; an unresolvable
    slug raises ``LookupError``. There is no implicit slug-to-id mapping —
    a fresh universe seeds no project rows, so any constant fallback would
    silently bind a scope name to whatever project happens to hold that id.
    """
    resolved: List[int] = []
    for project in project_scope:
        text = str(project).strip()
        if isinstance(project, int) or text.isdigit():
            resolved.append(int(project))
            continue
        try:
            resolved.append(resolve_project_id(conn, project))
        except db_backend.operational_error_types(conn) as exc:
            if db_backend.connection_is_postgres(conn):
                try:
                    conn.rollback()
                except Exception:
                    pass
            raise LookupError(f"project {project!r} not found") from exc
    return resolved


__all__ = ["normalize_project_scope"]
