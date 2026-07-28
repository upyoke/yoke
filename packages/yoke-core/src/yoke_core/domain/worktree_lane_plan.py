"""Resolve workflow-policy lane roles into branch and path plans."""

from __future__ import annotations

import os
from typing import Any, List, Mapping, Optional, Sequence, Tuple

from yoke_core.domain import db_backend
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
    *,
    authoritative_lanes: Optional[Sequence[Mapping[str, Any]]] = None,
) -> List[Tuple[str, ...]]:
    """Resolve branches and lane roles from the pinned workflow policy."""
    fallback_path = os.path.join(
        repo_root,
        worktrees_dir,
        f"YOK-{item_id}",
    )
    fallback = [(f"YOK-{item_id}", fallback_path, LANE_IMPLEMENTATION)]
    if authoritative_lanes is not None:
        role_order = {
            LANE_INTEGRATION: 0,
            LANE_IMPLEMENTATION: 1,
            LANE_WORKER: 2,
        }
        rows = sorted(
            authoritative_lanes,
            key=lambda row: (
                role_order.get(str(row.get("lane_role") or ""), 3),
                int(row.get("id") or 0),
            ),
        )
        return [
            (
                str(row.get("branch") or ""),
                os.path.join(repo_root, worktrees_dir, str(row.get("branch") or "")),
                str(row.get("lane_role") or ""),
                int(row.get("id") or 0),
            )
            for row in rows
        ]
    from yoke_core.domain.db_helpers import connect

    try:
        conn = connect(db_path)
    except Exception:
        return fallback
    try:
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
        existing_rows = conn.execute(
            "SELECT id, branch, COALESCE(path, '') AS path, lane_role "
            "FROM item_worktrees "
            f"WHERE item_id = {marker} AND state = 'active' "
            "ORDER BY CASE lane_role "
            "WHEN 'integration' THEN 0 "
            "WHEN 'implementation' THEN 1 ELSE 2 END, id",
            (int(item_id),),
        ).fetchall()
        if existing_rows:
            resolved = [
                (
                    *normalize_worktree_lane(
                        row["branch"],
                        row["path"],
                        repo_root,
                        worktrees_dir,
                    ),
                    row["lane_role"],
                    int(row["id"]),
                )
                for row in existing_rows
            ]
            present_roles = {str(row[2]) for row in resolved}
            if (
                LANE_INTEGRATION in policy.required_roles
                and LANE_INTEGRATION not in present_roles
            ):
                resolved.insert(
                    0,
                    (f"YOK-{item_id}", fallback_path, LANE_INTEGRATION, 0),
                )
            return resolved
        if LANE_IMPLEMENTATION in policy.allowed_roles:
            return [
                (f"YOK-{item_id}", fallback_path, LANE_IMPLEMENTATION, 0),
            ]
        if policy.required_roles == frozenset({LANE_WORKER}):
            return [(f"YOK-{item_id}", fallback_path, LANE_WORKER, 0)]
        return []
    finally:
        conn.close()


__all__ = [
    "normalize_worktree_lane",
    "resolve_worktree_lanes_for_item",
]
