"""Resolve structured work-item metadata into a bounded native session name."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.project_identity import (
    placeholder,
    render_item_ref,
    resolve_item_id,
)
from yoke_core.domain.session_launch_types import SessionLaunchError


MAX_SESSION_NAME_LENGTH = 160


def assignment_session_name(
    conn: Any,
    *,
    item_ref: str,
    project_id: int,
) -> str:
    """Return ``PREFIX-N: title`` from authoritative item columns."""
    item_id = resolve_item_id(conn, item_ref, project=project_id)
    if item_id is None:
        raise SessionLaunchError(
            "assignment_item_not_found",
            f"assignment item {item_ref!r} was not found; pass a current item ref",
        )
    row = conn.execute(
        f"SELECT project_id,title FROM items WHERE id={placeholder(conn)}",
        (item_id,),
    ).fetchone()
    if row is None or int(row[0]) != int(project_id):
        raise SessionLaunchError(
            "assignment_project_mismatch",
            "assignment item must belong to the launch project",
        )
    title = " ".join(str(row[1] or "").split())
    if not title:
        raise SessionLaunchError(
            "assignment_title_missing",
            "assignment item needs a title before it can launch a session",
        )
    name = f"{render_item_ref(conn, item_id, required=True)}: {title}"
    return name[:MAX_SESSION_NAME_LENGTH]


__all__ = ["MAX_SESSION_NAME_LENGTH", "assignment_session_name"]
