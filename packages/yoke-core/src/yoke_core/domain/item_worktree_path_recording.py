"""Guarded persistence of machine-local paths onto active item lanes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.workflow_item_binding_lock import (
    lock_item_workflow_bindings,
)


def _placeholder(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _dict_row(cursor: Any) -> dict[str, Any] | None:
    row = cursor.fetchone()
    if row is None:
        return None
    columns = [str(value[0]) for value in cursor.description]
    return dict(row) if hasattr(row, "keys") else dict(zip(columns, row))


def record_item_worktree_path(
    conn: Any,
    *,
    item_id: int,
    worktree_id: int,
    expected_branch: str,
    path: str,
) -> dict[str, Any]:
    """Record one machine-local path against an unchanged active lane."""
    clean_path = str(path).strip()
    clean_branch = str(expected_branch).strip()
    if not clean_path or not Path(clean_path).is_absolute():
        raise ValueError("item worktree path must be an absolute path")
    if not clean_branch:
        raise ValueError("expected item worktree branch must be non-empty")

    item_id = int(item_id)
    worktree_id = int(worktree_id)
    lock_item_workflow_bindings(conn, (item_id,))
    from yoke_core.domain.item_terminal_resources import (
        ensure_item_accepts_active_resources,
    )

    ensure_item_accepts_active_resources(conn, item_id)
    marker = _placeholder(conn)
    lock_suffix = " FOR UPDATE" if db_backend.connection_is_postgres(conn) else ""
    lane = _dict_row(conn.execute(
        "SELECT id, item_id, branch, lane_role, state "
        "FROM item_worktrees "
        f"WHERE id = {marker} AND item_id = {marker}{lock_suffix}",
        (worktree_id, item_id),
    ))
    if lane is None or str(lane["state"]) != "active":
        raise ValueError(
            f"item worktree lane {worktree_id} is no longer active for item "
            f"{item_id}"
        )
    if str(lane["branch"]) != clean_branch:
        raise ValueError(
            f"item worktree lane {worktree_id} branch changed from "
            f"{clean_branch!r} to {lane['branch']!r}"
        )

    owner = _dict_row(conn.execute(
        "SELECT id, item_id, branch FROM item_worktrees "
        f"WHERE path = {marker} AND state = 'active' AND id <> {marker}",
        (clean_path, worktree_id),
    ))
    if owner is not None:
        raise ValueError(
            f"active worktree path {clean_path!r} is already owned by "
            f"item {owner['item_id']} branch {owner['branch']!r}"
        )
    conn.execute(
        "UPDATE item_worktrees "
        f"SET path = {marker}, updated_at = {marker} "
        f"WHERE id = {marker} AND item_id = {marker} "
        f"AND branch = {marker} AND state = 'active'",
        (clean_path, iso8601_now(), worktree_id, item_id, clean_branch),
    )
    from yoke_core.domain.item_worktrees import list_item_worktrees

    return next(
        row
        for row in list_item_worktrees(conn, item_id, active_only=True)
        if int(row["id"]) == worktree_id
    )


__all__ = ["record_item_worktree_path"]
