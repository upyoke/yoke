"""Explicit repair for projects whose effective sync mode lacks usable auth."""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain.db_helpers import connect, query_rows
from yoke_core.domain.project_github_binding_active import (
    project_has_active_verified_github_binding,
)
from yoke_core.domain.project_identity import resolve_project
from yoke_core.domain.projects_github_sync_mode import (
    GITHUB_SYNC_BACKLOG_ONLY,
    GITHUB_SYNC_ENABLED,
)


def cmd_repair_unbound_enabled_sync_modes(
    *,
    project: Optional[str] = None,
    apply: bool = False,
    db_path: Optional[str] = None,
    conn: Optional[Any] = None,
) -> dict[str, Any]:
    """Find or normalize effectively-enabled projects without active bindings.

    Dry-run is the default. Legacy NULL/empty values count as effectively
    enabled because the compatibility reader resolves them that way.
    """
    owns_conn = conn is None
    if owns_conn:
        conn = connect(db_path)
    try:
        assert conn is not None
        selected_id: int | None = None
        if project is not None:
            ident = resolve_project(conn, project, required=True)
            assert ident is not None
            selected_id = ident.id
        sql = "SELECT id, slug, github_sync_mode FROM projects"
        params: tuple[Any, ...] = ()
        if selected_id is not None:
            sql += " WHERE id=%s"
            params = (selected_id,)
        sql += " ORDER BY id"
        candidates = []
        for row in query_rows(conn, sql, params):
            stored_mode = row["github_sync_mode"]
            effective_mode = str(stored_mode or "").strip() or GITHUB_SYNC_ENABLED
            if effective_mode != GITHUB_SYNC_ENABLED:
                continue
            project_id = int(row["id"])
            if project_has_active_verified_github_binding(conn, project_id):
                continue
            candidates.append(
                {
                    "id": project_id,
                    "slug": str(row["slug"]),
                    "stored_mode": stored_mode,
                    "effective_mode": effective_mode,
                }
            )

        normalized = 0
        if apply:
            for candidate in candidates:
                conn.execute(
                    "UPDATE projects SET github_sync_mode=%s WHERE id=%s",
                    (GITHUB_SYNC_BACKLOG_ONLY, candidate["id"]),
                )
                normalized += 1
            if owns_conn:
                conn.commit()
        return {
            "applied": bool(apply),
            "matched": len(candidates),
            "normalized": normalized,
            "projects": candidates,
        }
    finally:
        if owns_conn and conn is not None:
            conn.close()


__all__ = ["cmd_repair_unbound_enabled_sync_modes"]
