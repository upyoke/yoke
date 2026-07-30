"""Project-roster resolution for the resync linkage stage.

Determines which project slugs a resync run covers and partitions them
by per-project GitHub sync mode: backlog-only projects are excluded
from the fetch and carry the sync-disabled sentinel downstream.
"""

from __future__ import annotations

from typing import Dict, Tuple


def resolve_fetch_roster(
    conn,
    *,
    project: str = "",
    table_exists,
) -> Tuple[set, Dict[str, str]]:
    """Return ``(fetch_projects, sync_disabled)`` for one resync run.

    The roster comes from work represented in the backlog plus active
    repository bindings (which may have GitHub-only orphans). Repository
    authority does not come from the legacy projects projection; the
    canonical resolver returns bound repo metadata and its matching
    bearer token together.
    """
    from yoke_core.domain import db_backend
    from yoke_core.domain.projects_github_sync_mode import (
        GITHUB_SYNC_ENABLED,
        resolve_github_sync_mode,
    )

    project_roster: set[str] = {project} if project else {"yoke"}
    if not project:
        try:
            rows = conn.execute(
                "SELECT DISTINCT COALESCE(p.slug, 'yoke') "
                "FROM items i LEFT JOIN projects p ON i.project_id = p.id"
            ).fetchall()
            for row in rows:
                project_roster.add(row[0])
        except db_backend.operational_error_types(conn):
            conn.rollback()
        if table_exists("project_github_repo_bindings"):
            try:
                rows = conn.execute(
                    "SELECT DISTINCT p.slug "
                    "FROM project_github_repo_bindings b "
                    "JOIN projects p ON p.id = b.project_id "
                    "WHERE b.status = 'active'"
                ).fetchall()
                for row in rows:
                    project_roster.add(row[0])
            except db_backend.operational_error_types(conn):
                conn.rollback()

    # Per-project GitHub sync switch: backlog-only projects are excluded
    # from the fetch entirely and carry the sync-disabled sentinel so no
    # downstream stage classifies (or repairs) their items.
    sync_disabled: Dict[str, str] = {}
    for slug in project_roster:
        mode = resolve_github_sync_mode(slug, conn=conn)
        if mode != GITHUB_SYNC_ENABLED:
            sync_disabled[slug] = mode
    return project_roster.difference(sync_disabled), sync_disabled


__all__ = ["resolve_fetch_roster"]
