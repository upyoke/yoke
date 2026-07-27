"""Universal item-worktree projection for path-claim guard resolution."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.project_checkout_locations import worktree_path_for_branch


def universal_item_worktree_paths(
    conn: Any,
    *,
    item_id: int,
    project_id: Optional[int],
) -> Optional[Dict[str, Any]]:
    """Return active universal-lane path fields for claim guards."""
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    rows = conn.execute(
        "SELECT lane_role, branch, path FROM item_worktrees "
        f"WHERE item_id = {marker} AND state = 'active' ORDER BY id",
        (item_id,),
    ).fetchall()
    lanes = []
    for row in rows:
        values = dict(row) if hasattr(row, "keys") else {
            "lane_role": row[0], "branch": row[1], "path": row[2],
        }
        branch = str(values["branch"] or "").strip()
        raw_path = str(values["path"] or "").strip()
        if not branch:
            continue
        path = (
            Path(raw_path)
            if raw_path
            else worktree_path_for_branch(project_id, branch)
        )
        if path is None:
            continue
        try:
            resolved = path.expanduser().resolve()
        except OSError:
            continue
        lanes.append((
            str(values["lane_role"] or ""), branch, str(resolved),
        ))
    if not lanes:
        return None
    task_lanes = any(
        role in {"worker", "integration"}
        for role, _branch, _path in lanes
    )
    branch_paths = tuple(
        (branch, path) for _role, branch, path in lanes
    )
    return {
        "task_lanes": task_lanes,
        "worktree_branch": (
            branch_paths[0][0]
            if not task_lanes and len(branch_paths) == 1
            else None
        ),
        "worktree_path": (
            branch_paths[0][1]
            if not task_lanes and len(branch_paths) == 1
            else None
        ),
        "chain_worktrees": branch_paths if task_lanes else (),
    }


__all__ = ["universal_item_worktree_paths"]
