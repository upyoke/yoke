"""Engine checks for worktree removal and active lane claims."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from yoke_contracts.hook_runner.bash_paths import resolve_bash_path
from yoke_contracts.hook_runner.rm_lane_guard import (
    resolve_rm_targets as resolve_rm_targets,
    rm_worktree_targets as rm_worktree_targets,
    worktree_status_threats as worktree_status_threats,
)


def worktree_remove_targets(args: list[str], cwd: str) -> list[str]:
    targets: list[str] = []
    for token in args[2:]:
        if token == "--":
            continue
        if token in ("-f", "--force"):
            continue
        if token.startswith("-"):
            continue
        targets.append(resolve_bash_path(token, cwd))
    return targets


def _path_inside(child: str, parent: str) -> bool:
    child_path = Path(child).expanduser().resolve(strict=False)
    parent_path = Path(parent).expanduser().resolve(strict=False)
    return child_path == parent_path or parent_path in child_path.parents


def claimed_worktree_threats(targets: Iterable[str]) -> list[str]:
    try:
        from yoke_core.domain.db_helpers import connect
        from yoke_core.domain.session_claimed_worktrees import claimed_worktrees
    except Exception:
        return []
    try:
        conn = connect()
    except Exception:
        return []
    try:
        rows = conn.execute(
            "SELECT DISTINCT session_id FROM work_claims "
            "WHERE released_at IS NULL AND session_id IS NOT NULL"
        ).fetchall()
        threats: list[str] = []
        for row in rows:
            session_id = row["session_id"] if hasattr(row, "keys") else row[0]
            for claim in claimed_worktrees(conn, session_id=str(session_id)):
                for target in targets:
                    # A target inside a lane deletes part of it, not the
                    # lane; only the lane itself or an ancestor counts.
                    if _path_inside(claim.worktree_path, target):
                        label = (
                            f"{claim.worktree_path} active claim "
                            f"session={session_id} item={claim.item_id}"
                        )
                        if claim.task_num is not None:
                            label += f" task={claim.task_num}"
                        threats.append(label)
        return threats
    except Exception:
        return []
    finally:
        try:
            conn.close()
        except Exception:
            pass
