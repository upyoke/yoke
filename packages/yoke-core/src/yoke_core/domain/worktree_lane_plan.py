"""Resolve workflow-policy lane roles into branch and path plans."""

from __future__ import annotations

import os
from typing import List, Optional, Tuple

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.workflow_behavior import (
    LANE_IMPLEMENTATION,
    LANE_INTEGRATION,
    LANE_WORKER,
    worktree_lane_policy,
)
from yoke_core.domain.workflow_runtime import load_item_workflow_runtime


def normalize_worktree_lane(
    branch: str,
    path: str,
    repo_root: str,
    worktrees_dir: str,
) -> Tuple[str, str]:
    """Return one complete branch/path pair from either stored component."""
    branch = (branch or "").strip()
    path = (path or "").strip()
    if not path and branch:
        path = os.path.join(repo_root, worktrees_dir, branch)
    if not branch and path:
        branch = os.path.basename(path)
    if path and not os.path.isabs(path):
        path = os.path.join(repo_root, path)
    return branch, path


def resolve_worktree_lanes_for_item(
    item_id: int,
    repo_root: str,
    worktrees_dir: str,
    db_path: Optional[str] = None,
) -> List[Tuple[str, str, str]]:
    """Resolve branches and lane roles from the pinned workflow policy."""
    fallback_path = os.path.join(
        repo_root,
        worktrees_dir,
        f"YOK-{item_id}",
    )
    fallback = [(f"YOK-{item_id}", fallback_path, LANE_IMPLEMENTATION)]
    from yoke_core.domain.db_helpers import connect

    try:
        conn = connect(db_path)
    except Exception:
        return fallback
    try:
        if not _table_exists(conn, "items"):
            return fallback
        marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
        if (
            conn.execute(
                f"SELECT 1 FROM items WHERE id = {marker}",
                (int(item_id),),
            ).fetchone()
            is None
        ):
            return fallback
        runtime = load_item_workflow_runtime(conn, int(item_id))
        policy = worktree_lane_policy(runtime)
        if _table_exists(conn, "item_worktrees"):
            existing_rows = conn.execute(
                "SELECT branch, COALESCE(path, '') AS path, lane_role "
                "FROM item_worktrees "
                f"WHERE item_id = {marker} AND state = 'active' "
                "ORDER BY CASE lane_role "
                "WHEN 'integration' THEN 0 "
                "WHEN 'implementation' THEN 1 ELSE 2 END, id",
                (int(item_id),),
            ).fetchall()
            if existing_rows:
                return [
                    (
                        *normalize_worktree_lane(
                            row["branch"],
                            row["path"],
                            repo_root,
                            worktrees_dir,
                        ),
                        row["lane_role"],
                    )
                    for row in existing_rows
                ]
        if LANE_IMPLEMENTATION in policy.allowed_roles:
            return fallback

        rows = []
        if _table_exists(conn, "epic_dispatch_chains"):
            rows = conn.execute(
                "SELECT COALESCE(worktree, '') AS branch, "
                "COALESCE(worktree_path, '') AS path "
                "FROM epic_dispatch_chains "
                f"WHERE epic_id = {marker} "
                "AND COALESCE(worktree, '') <> '' ORDER BY worktree",
                (int(item_id),),
            ).fetchall()
        workers = [
            (
                *normalize_worktree_lane(
                    row["branch"],
                    row["path"],
                    repo_root,
                    worktrees_dir,
                ),
                LANE_WORKER,
            )
            for row in rows
        ]
        if LANE_INTEGRATION not in policy.required_roles:
            return workers or [(f"YOK-{item_id}", fallback_path, LANE_WORKER)]

        integration_branch = f"YOK-{item_id}"
        if integration_branch in {branch for branch, _path, _role in workers}:
            integration_branch += "-integration"
        integration = (
            integration_branch,
            os.path.join(repo_root, worktrees_dir, integration_branch),
            LANE_INTEGRATION,
        )
        return [integration, *workers]
    finally:
        conn.close()


__all__ = [
    "normalize_worktree_lane",
    "resolve_worktree_lanes_for_item",
]
