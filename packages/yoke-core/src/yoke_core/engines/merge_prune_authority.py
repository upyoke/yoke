"""Control-plane proofs that a lane may be pruned: terminal owner, idle authority.

Pruning a worktree or branch is only safe when the database names exactly one
owner for it, that owner is terminal, and nothing live still holds it — a
work claim, a planned or active path claim, or a session whose workspace is
the lane. Every lookup failure reads as "cannot prove", which preserves the
lane; the git-side sweep in ``merge_worktree_safe_prune`` consumes these
verdicts through ``merge.prune.authority_verdict`` so they run wherever the
control plane lives.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from yoke_contracts.lifecycle_status import TASK_TERMINAL_SUCCESS
from yoke_core.domain import db_backend


_ITEM_TERMINAL = frozenset({"done", "cancelled"})


@dataclass(frozen=True)
class LaneOwner:
    kind: str
    item_id: int
    task_num: int | None = None


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _row_value(row: Any, key: str, index: int) -> Any:
    return row[key] if hasattr(row, "keys") else row[index]


def terminal_owner(
    conn: Any,
    *,
    branch: str,
    path: Path | None,
) -> LaneOwner | None:
    """Return the unique terminal DB owner, never infer one from a name."""
    marker = _p(conn)
    owners: set[LaneOwner] = set()
    try:
        where = f"iw.branch = {marker}"
        params: tuple[Any, ...] = (branch,)
        if path is not None:
            where += f" OR iw.path = {marker}"
            params = (branch, str(path))
        rows = conn.execute(
            "SELECT iw.id AS lane_id, iw.item_id, i.status "
            "FROM item_worktrees iw JOIN items i ON i.id = iw.item_id "
            f"WHERE {where}",
            params,
        ).fetchall()
        for row in rows:
            lane_id = int(_row_value(row, "lane_id", 0))
            item_id = int(_row_value(row, "item_id", 1))
            task_rows = conn.execute(
                "SELECT epic_id, task_num, status FROM epic_tasks "
                f"WHERE item_worktree_id = {marker}",
                (lane_id,),
            ).fetchall()
            if not task_rows:
                if str(_row_value(row, "status", 2)) not in _ITEM_TERMINAL:
                    return None
                owners.add(LaneOwner("item", item_id))
                continue
            for task_row in task_rows:
                if str(_row_value(task_row, "status", 2)) not in TASK_TERMINAL_SUCCESS:
                    return None
                owners.add(
                    LaneOwner(
                        "epic_task",
                        int(_row_value(task_row, "epic_id", 0)),
                        int(_row_value(task_row, "task_num", 1)),
                    )
                )
        if not rows:
            return None
        if any(
            owner.item_id not in {int(_row_value(row, "item_id", 1)) for row in rows}
            for owner in owners
        ):
            # A task link whose parent disagrees with the universal lane owner
            # is corrupt; pruning must preserve it for diagnosis.
            return None
    except Exception:  # noqa: BLE001 - missing/stale DB shape means preserve
        return None
    return next(iter(owners)) if len(owners) == 1 else None


def has_active_authority(
    conn: Any,
    owner: LaneOwner,
    path: Path | None,
) -> bool:
    """Conservatively treat lookup failure as active authority."""
    marker = _p(conn)
    from yoke_core.domain.work_claim_targets import scope_int_sql

    try:
        if owner.kind == "item":
            item_scope = scope_int_sql(conn, "scope", "item_id")
            row = conn.execute(
                "SELECT 1 FROM work_claims WHERE released_at IS NULL "
                f"AND target_kind = 'item' AND {item_scope} = {marker} LIMIT 1",
                (owner.item_id,),
            ).fetchone()
        else:
            epic_scope = scope_int_sql(conn, "scope", "epic_id")
            task_scope = scope_int_sql(conn, "scope", "task_num")
            row = conn.execute(
                "SELECT 1 FROM work_claims WHERE released_at IS NULL "
                "AND target_kind = 'epic_task' "
                f"AND {epic_scope} = {marker} "
                f"AND {task_scope} = {marker} LIMIT 1",
                (owner.item_id, owner.task_num),
            ).fetchone()
        if row is not None:
            return True
        row = conn.execute(
            "SELECT 1 FROM path_claims "
            "WHERE state IN ('planned', 'blocked', 'active') "
            f"AND owner_kind = 'item' AND owner_item_id = {marker} "
            "LIMIT 1",
            (owner.item_id,),
        ).fetchone()
        if row is not None:
            return True
        if path is not None:
            row = conn.execute(
                "SELECT 1 FROM harness_sessions WHERE ended_at IS NULL "
                f"AND workspace = {marker} LIMIT 1",
                (str(path),),
            ).fetchone()
            if row is not None:
                return True
    except Exception:  # noqa: BLE001 - fail closed
        return True
    return False


def item_cleanup_authority_blocks_prune(conn: Any, item_id: int) -> bool:
    """Return true when item authority is active or cannot be proven idle."""
    return has_active_authority(conn, LaneOwner("item", int(item_id)), None)


__all__ = [
    "LaneOwner",
    "has_active_authority",
    "item_cleanup_authority_blocks_prune",
    "terminal_owner",
]
