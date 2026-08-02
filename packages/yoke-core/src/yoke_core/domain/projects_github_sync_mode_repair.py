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
    GITHUB_SYNC_DISABLED,
    GITHUB_SYNC_ENABLED,
    VALID_GITHUB_SYNC_MODES,
)
from yoke_core.domain.schema_common import _column_exists as _schema_column_exists


REPAIR_ACTION_SET_DISABLED = "set_github_sync_mode_disabled"
REPAIR_ACTION_CLEAR_REPO_PROJECTION = "clear_github_repo_projection"
REPAIR_ACTION_REMOVE_CAPABILITY_PROJECTION = "remove_github_capability_projection"
REPAIR_ACTION_CLEAR_COMPACT_PENDING = "clear_github_body_compact_pending"

COMPACT_PENDING_COLUMN = "github_body_compact_pending"


def _compact_pending_counts_by_project(conn: Any) -> dict[int, int]:
    """Count items still flagged as compact-mirror pending, per project.

    The flag is stamped and cleared only by a successful body sync, so a
    project whose sync is off can never clear one through the normal path.
    Absent on minimal fixture schemas, which report no counts at all.
    """
    if not _schema_column_exists(conn, "items", COMPACT_PENDING_COLUMN):
        return {}
    rows = query_rows(
        conn,
        f"SELECT project_id, COUNT(*) AS pending FROM items "
        f"WHERE {COMPACT_PENDING_COLUMN} IS NOT NULL GROUP BY project_id",
        (),
    )
    return {int(row["project_id"]): int(row["pending"]) for row in rows}


def cmd_repair_unbound_enabled_sync_modes(
    *,
    project: Optional[str] = None,
    apply: bool = False,
    db_path: Optional[str] = None,
    conn: Optional[Any] = None,
) -> dict[str, Any]:
    """Find or normalize unsafe modes and stale unbound projections.

    Dry-run is the default. Legacy, empty, and unrecognized values normalize
    to ``disabled``. A project with no repository-binding row also cannot
    retain the binding-owned ``projects.github_repo`` or canonical GitHub
    capability projection. A project whose effective mode is ``disabled``
    also cannot retain compact-mirror pending flags on its items: only a
    successful body sync clears one, and every sync surface skips a
    disabled project, so the flag would otherwise strand permanently.

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
        compact_pending = _compact_pending_counts_by_project(conn)
        candidates = []
        for row in query_rows(conn, sql, params):
            stored_mode = row["github_sync_mode"]
            cleaned_mode = str(stored_mode or "").strip()
            effective_mode = (
                cleaned_mode
                if cleaned_mode in VALID_GITHUB_SYNC_MODES
                else GITHUB_SYNC_DISABLED
            )
            needs_normalization = cleaned_mode != effective_mode
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
                needs_normalization
                or (
                    effective_mode == GITHUB_SYNC_ENABLED
                    and not active_verified_binding
                )
                or (
                    has_stale_unbound_projection
                    and effective_mode != GITHUB_SYNC_DISABLED
                )
            ):
                actions.append(
                    {
                        "action": REPAIR_ACTION_SET_DISABLED,
                        "column": "github_sync_mode",
                        "from": stored_mode,
                        "to": GITHUB_SYNC_DISABLED,
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
            pending_count = compact_pending.get(project_id, 0)
            if effective_mode == GITHUB_SYNC_DISABLED and pending_count:
                actions.append(
                    {
                        "action": REPAIR_ACTION_CLEAR_COMPACT_PENDING,
                        "table": "items",
                        "column": COMPACT_PENDING_COLUMN,
                        "items": pending_count,
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
                    if action["action"] == REPAIR_ACTION_SET_DISABLED:
                        conn.execute(
                            "UPDATE projects SET github_sync_mode=%s WHERE id=%s",
                            (GITHUB_SYNC_DISABLED, candidate["id"]),
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
                    elif action["action"] == REPAIR_ACTION_CLEAR_COMPACT_PENDING:
                        conn.execute(
                            f"UPDATE items SET {COMPACT_PENDING_COLUMN}=NULL "
                            f"WHERE project_id=%s "
                            f"AND {COMPACT_PENDING_COLUMN} IS NOT NULL",
                            (candidate["id"],),
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
    "COMPACT_PENDING_COLUMN",
    "REPAIR_ACTION_CLEAR_COMPACT_PENDING",
    "REPAIR_ACTION_CLEAR_REPO_PROJECTION",
    "REPAIR_ACTION_REMOVE_CAPABILITY_PROJECTION",
    "REPAIR_ACTION_SET_DISABLED",
    "cmd_repair_unbound_enabled_sync_modes",
]
