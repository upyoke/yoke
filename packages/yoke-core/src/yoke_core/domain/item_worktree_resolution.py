"""Universal lane resolution shared by item worktree consumers.

Operational readers resolve active rows. Audit and pruning callers may opt
into released history explicitly; no reader falls back to retired worktree
columns on ``items`` or generated-child tables.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.worktree_paths import _run, is_git_worktree

_ACTIVE_LANE_ORDER = (
    "CASE lane_role WHEN 'integration' THEN 0 "
    "WHEN 'implementation' THEN 1 WHEN 'worker' THEN 2 ELSE 3 END"
)


def _placeholder(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def primary_item_worktree_branch_sql(item_id_expression: str) -> str:
    """Return a correlated SQL expression for an item's primary active branch."""
    return (
        "(SELECT iw.branch FROM item_worktrees iw "
        f"WHERE iw.item_id = {item_id_expression} AND iw.state = 'active' "
        f"ORDER BY {_ACTIVE_LANE_ORDER}, iw.id LIMIT 1)"
    )


def recorded_item_worktree_records(
    conn: Any,
    item_id: int,
    repo_root: str,
    worktrees_dir: str,
    *,
    active_only: bool = True,
    lane_role: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Return resolved universal lane rows in operational priority order."""
    marker = _placeholder(conn)
    clauses = [f"item_id = {marker}"]
    params: list[Any] = [int(item_id)]
    if active_only:
        clauses.append("state = 'active'")
    if lane_role is not None:
        clauses.append(f"lane_role = {marker}")
        params.append(lane_role)
    rows = conn.execute(
        "SELECT id, item_id, branch, COALESCE(path, '') AS path, "
        "lane_role, state, created_at, updated_at, released_at "
        "FROM item_worktrees WHERE "
        + " AND ".join(clauses)
        + f" ORDER BY {_ACTIVE_LANE_ORDER}, id",
        tuple(params),
    ).fetchall()
    records: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for row in rows:
        values = dict(row) if hasattr(row, "keys") else {
            "id": row[0],
            "item_id": row[1],
            "branch": row[2],
            "path": row[3],
            "lane_role": row[4],
            "state": row[5],
            "created_at": row[6],
            "updated_at": row[7],
            "released_at": row[8],
        }
        branch, path = _complete_lane(
            str(values.get("branch") or ""),
            str(values.get("path") or ""),
            repo_root,
            worktrees_dir,
        )
        if not path or path in seen_paths:
            continue
        seen_paths.add(path)
        values["branch"] = branch
        values["path"] = path
        records.append(values)
    return records


def recorded_item_worktree_lanes(
    conn,
    item_id: int,
    repo_root: str,
    worktrees_dir: str,
    *,
    active_only: bool = True,
) -> tuple[list[tuple[str, str]], str]:
    """Return universal branch/path pairs and their stable scope label."""
    records = recorded_item_worktree_records(
        conn,
        item_id,
        repo_root,
        worktrees_dir,
        active_only=active_only,
    )
    return [
        (str(row["branch"]), str(row["path"])) for row in records
    ], "item-lanes"


def resolve_item_id_by_worktree_name(conn: Any, name: str) -> Optional[int]:
    """Recover the internal item id that owns a worktree/branch NAME.

    The inverse of
    :func:`yoke_core.domain.worktree_naming.worktree_name_for_item`. Given a
    branch name or worktree-directory basename, return the owning
    ``item_worktrees.item_id``. A recorded ``branch`` is matched first, then a
    recorded ``path`` whose basename equals the name — so worktrees created
    under the public-ref scheme (``PREFIX-{project_sequence}``) or the legacy
    ``YOK-{internal_id}`` scheme both resolve to the correct internal id. An
    active lane wins over a released one when several rows share the name.
    Returns ``None`` when nothing matches or the registry is unavailable.
    """
    clean = (name or "").strip().strip("/")
    if not clean:
        return None
    marker = _placeholder(conn)
    order = "ORDER BY CASE WHEN state = 'active' THEN 0 ELSE 1 END, id DESC"
    try:
        row = conn.execute(
            f"SELECT item_id FROM item_worktrees WHERE branch = {marker} "
            f"{order} LIMIT 1",
            (clean,),
        ).fetchone()
        if row is None:
            row = conn.execute(
                f"SELECT item_id FROM item_worktrees "
                f"WHERE path = {marker} OR path LIKE {marker} {order} LIMIT 1",
                (clean, f"%/{clean}"),
            ).fetchone()
    except Exception:  # noqa: BLE001 - missing table / minimal schema
        return None
    if row is None:
        return None
    value = row["item_id"] if hasattr(row, "keys") else row[0]
    return int(value)


def resolve_live_branch(path: str, fallback: str) -> str:
    """Return the checked-out branch when the lane exists locally."""
    if not is_git_worktree(path):
        return fallback
    result = _run(["git", "branch", "--show-current"], cwd=path)
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    return fallback


def _complete_lane(
    branch: str,
    path: str,
    repo_root: str,
    worktrees_dir: str,
) -> tuple[str, str]:
    branch = (branch or "").strip()
    path = (path or "").strip()
    if not path and branch:
        path = os.path.join(repo_root, worktrees_dir, branch)
    if not branch and path:
        branch = os.path.basename(path)
    return branch, path


__all__ = [
    "primary_item_worktree_branch_sql",
    "recorded_item_worktree_lanes",
    "recorded_item_worktree_records",
    "resolve_item_id_by_worktree_name",
    "resolve_live_branch",
]
