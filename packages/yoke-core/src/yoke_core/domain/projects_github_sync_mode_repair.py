"""Explicit repair for unsafe sync modes and unbound GitHub projections."""

from __future__ import annotations

from typing import Any, Optional

from yoke_contracts.github_app_tokens import GITHUB_CAPABILITY_TYPE

from yoke_core.domain.db_helpers import connect, query_rows
from yoke_core.domain.project_github_binding_active import (
    project_has_active_verified_github_binding,
)
from yoke_core.domain.project_identity import resolve_project
from yoke_core.domain.projects_github_sync_mode import (
    GITHUB_SYNC_BACKLOG_ONLY,
    GITHUB_SYNC_ENABLED,
)


REPAIR_ACTION_SET_BACKLOG_ONLY = "set_github_sync_mode_backlog_only"
REPAIR_ACTION_CLEAR_REPO_PROJECTION = "clear_github_repo_projection"
REPAIR_ACTION_REMOVE_CAPABILITY_PROJECTION = "remove_github_capability_projection"


def cmd_repair_unbound_enabled_sync_modes(
    *,
    project: Optional[str] = None,
    apply: bool = False,
    db_path: Optional[str] = None,
    conn: Optional[Any] = None,
) -> dict[str, Any]:
    """Find or normalize unsafe modes and stale unbound projections.

    Dry-run is the default. Legacy NULL/empty values count as effectively
    enabled because the compatibility reader resolves them that way. A project
    with no repository-binding row also cannot retain the binding-owned
    ``projects.github_repo`` or canonical GitHub capability projection.

    Retired ``capability_secrets`` and shared installation rows are deliberately
    outside this repair's mutation boundary.
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
        sql = (
            "SELECT p.id, p.slug, p.github_sync_mode, p.github_repo, "
            "EXISTS (SELECT 1 FROM project_github_repo_bindings b "
            "WHERE b.project_id=p.id) AS has_binding, "
            "EXISTS (SELECT 1 FROM project_capabilities c "
            "WHERE c.project_id=p.id AND c.type=%s) "
            "AS has_github_capability FROM projects p"
        )
        params: tuple[Any, ...] = (GITHUB_CAPABILITY_TYPE,)
        if selected_id is not None:
            sql += " WHERE p.id=%s"
            params += (selected_id,)
        sql += " ORDER BY p.id"
        candidates = []
        for row in query_rows(conn, sql, params):
            stored_mode = row["github_sync_mode"]
            effective_mode = str(stored_mode or "").strip() or GITHUB_SYNC_ENABLED
            project_id = int(row["id"])
            has_binding = bool(row["has_binding"])
            has_github_capability = bool(row["has_github_capability"])
            github_repo = str(row["github_repo"] or "").strip()
            active_verified_binding = False
            if effective_mode == GITHUB_SYNC_ENABLED:
                active_verified_binding = project_has_active_verified_github_binding(
                    conn, project_id
                )

            actions: list[dict[str, Any]] = []
            has_stale_unbound_projection = not has_binding and bool(
                github_repo or has_github_capability
            )
            if (
                effective_mode == GITHUB_SYNC_ENABLED and not active_verified_binding
            ) or (
                has_stale_unbound_projection
                and effective_mode != GITHUB_SYNC_BACKLOG_ONLY
            ):
                actions.append(
                    {
                        "action": REPAIR_ACTION_SET_BACKLOG_ONLY,
                        "column": "github_sync_mode",
                        "from": stored_mode,
                        "to": GITHUB_SYNC_BACKLOG_ONLY,
                    }
                )
            if not has_binding and github_repo:
                actions.append(
                    {
                        "action": REPAIR_ACTION_CLEAR_REPO_PROJECTION,
                        "column": "github_repo",
                        "from": github_repo,
                        "to": None,
                    }
                )
            if not has_binding and has_github_capability:
                actions.append(
                    {
                        "action": REPAIR_ACTION_REMOVE_CAPABILITY_PROJECTION,
                        "table": "project_capabilities",
                        "type": GITHUB_CAPABILITY_TYPE,
                    }
                )
            if not actions:
                continue
            candidates.append(
                {
                    "id": project_id,
                    "slug": str(row["slug"]),
                    "stored_mode": stored_mode,
                    "effective_mode": effective_mode,
                    "bound": has_binding,
                    "active_verified_binding": active_verified_binding,
                    "actions": actions,
                }
            )

        normalized = 0
        if apply:
            for candidate in candidates:
                for action in candidate["actions"]:
                    if action["action"] == REPAIR_ACTION_SET_BACKLOG_ONLY:
                        conn.execute(
                            "UPDATE projects SET github_sync_mode=%s WHERE id=%s",
                            (GITHUB_SYNC_BACKLOG_ONLY, candidate["id"]),
                        )
                    elif action["action"] == REPAIR_ACTION_CLEAR_REPO_PROJECTION:
                        conn.execute(
                            "UPDATE projects SET github_repo=NULL WHERE id=%s",
                            (candidate["id"],),
                        )
                    elif action["action"] == REPAIR_ACTION_REMOVE_CAPABILITY_PROJECTION:
                        conn.execute(
                            "DELETE FROM project_capabilities "
                            "WHERE project_id=%s AND type=%s",
                            (candidate["id"], GITHUB_CAPABILITY_TYPE),
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


__all__ = [
    "REPAIR_ACTION_CLEAR_REPO_PROJECTION",
    "REPAIR_ACTION_REMOVE_CAPABILITY_PROJECTION",
    "REPAIR_ACTION_SET_BACKLOG_ONLY",
    "cmd_repair_unbound_enabled_sync_modes",
]
