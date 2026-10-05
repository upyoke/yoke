"""Missing-project refusals on the caller's own connection and authority."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Collection

from yoke_contracts.project_defaults import (
    MissingProjectError,
    default_project_for_directory,
    missing_project_message,
)


def missing_project_on_connection(
    conn: Any,
    *,
    actor_id: int | None = None,
    visible_project_ids: Collection[int] | None = None,
) -> str:
    from yoke_core.domain.actor_project_visibility import actor_visible_project_ids
    from yoke_core.domain.project_identity import row_value
    from yoke_core.domain.project_retirement import active_projects_where

    visible = visible_project_ids
    if visible is None:
        visible = actor_visible_project_ids(conn, actor_id)
    rows = conn.execute(
        "SELECT id, slug FROM projects" + active_projects_where(conn) + " ORDER BY id"
    ).fetchall()
    names = [
        str(row_value(row, "slug", 1))
        for row in rows
        if visible is None or int(row_value(row, "id", 0)) in visible
    ]
    return missing_project_message(names)


def required_local_project(
    directory: str | Path,
    project: str | None = None,
    *,
    env=None,
) -> str:
    """Explicit value, caller environment, then caller checkout; never a slug guess."""
    environ = os.environ if env is None else env
    selected = str(project or environ.get("YOKE_PROJECT") or "").strip()
    selected = selected or default_project_for_directory(directory)
    if selected:
        return selected
    from yoke_core.domain.control_plane_transport import relay

    try:
        result = relay("projects.list", {"fields": ["id", "slug"]})
        message = missing_project_message([str(row["slug"]) for row in result["rows"]])
    except Exception as exc:  # noqa: BLE001 - preserve roster failure in the refusal
        message = missing_project_message([], unavailable=str(exc))
    raise MissingProjectError(message)
