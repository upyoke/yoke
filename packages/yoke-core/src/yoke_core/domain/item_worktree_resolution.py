"""Recorded lane resolution shared by item worktree readers."""

from __future__ import annotations

import os

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.worktree_paths import _run, is_git_worktree


def _placeholder(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def recorded_item_worktree_lanes(
    conn,
    item_id: int,
    repo_root: str,
    worktrees_dir: str,
) -> tuple[list[tuple[str, str]], str]:
    """Return recorded lanes and the scope naming their storage source."""
    universal = _universal_lanes(
        conn, item_id, repo_root, worktrees_dir,
    )
    if universal:
        return universal, "item-lanes"
    return (
        _legacy_task_lanes(conn, item_id, repo_root, worktrees_dir),
        "epic-tasks",
    )


def resolve_live_branch(path: str, fallback: str) -> str:
    """Return the checked-out branch when the lane exists locally."""
    if not is_git_worktree(path):
        return fallback
    result = _run(["git", "branch", "--show-current"], cwd=path)
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    return fallback


def _universal_lanes(
    conn,
    item_id: int,
    repo_root: str,
    worktrees_dir: str,
) -> list[tuple[str, str]]:
    if not _table_exists(conn, "item_worktrees"):
        return []
    marker = _placeholder(conn)
    rows = conn.execute(
        "SELECT branch, COALESCE(path, '') AS path "
        "FROM item_worktrees "
        f"WHERE item_id = {marker} AND state = 'active' "
        "ORDER BY CASE lane_role WHEN 'integration' THEN 0 "
        "WHEN 'implementation' THEN 1 ELSE 2 END, id",
        (int(item_id),),
    ).fetchall()
    return _dedupe([
        _complete_lane(
            row["branch"], row["path"], repo_root, worktrees_dir,
        )
        for row in rows
    ])


def _legacy_task_lanes(
    conn,
    item_id: int,
    repo_root: str,
    worktrees_dir: str,
) -> list[tuple[str, str]]:
    lanes: list[tuple[str, str]] = []
    marker = _placeholder(conn)
    if _table_exists(conn, "epic_dispatch_chains"):
        rows = conn.execute(
            "SELECT COALESCE(worktree, '') AS branch, "
            "COALESCE(worktree_path, '') AS path "
            "FROM epic_dispatch_chains "
            f"WHERE epic_id = {marker} "
            "AND COALESCE(worktree, '') <> '' ORDER BY worktree",
            (str(item_id),),
        ).fetchall()
        lanes.extend(
            _complete_lane(
                row["branch"], row["path"], repo_root, worktrees_dir,
            )
            for row in rows
        )
    if not lanes and _table_exists(conn, "epic_tasks"):
        rows = conn.execute(
            "SELECT COALESCE(NULLIF(branch, ''), "
            "NULLIF(worktree, ''), '') AS branch, "
            "COALESCE(worktree_path, '') AS path FROM epic_tasks "
            f"WHERE epic_id = {marker} AND ("
            "COALESCE(NULLIF(branch, ''), NULLIF(worktree, ''), '') <> '' "
            "OR COALESCE(worktree_path, '') <> '') ORDER BY task_num",
            (str(item_id),),
        ).fetchall()
        lanes.extend(
            _complete_lane(
                row["branch"], row["path"], repo_root, worktrees_dir,
            )
            for row in rows
        )
    return _dedupe(lanes)


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


def _dedupe(
    lanes: list[tuple[str, str]],
) -> list[tuple[str, str]]:
    unique: list[tuple[str, str]] = []
    seen: set[str] = set()
    for branch, path in lanes:
        if path and path not in seen:
            seen.add(path)
            unique.append((branch, path))
    return unique


__all__ = ["recorded_item_worktree_lanes", "resolve_live_branch"]
