"""Resolve a harness session's claim-derived worktree authority.

A session's authority to write under a worktree is its **active
work_claims**. This helper is the canonical reader: given a session id,
return the list of ``(item_id, task_num, worktree_path)`` tuples the
session currently owns through ``work_claims``. The session-cwd lint
consumes this set per tool call to decide whether a target path lands
under a claimed worktree, under the main control plane, or under a
free-path allowlist.

The resolution is small (typically 1-3 worktrees + control plane); no
caching is required. Released claims are excluded. Items without a
populated worktree branch (e.g. ``--no-worktree`` evidence-only items)
contribute no worktree row — the session still holds the work claim,
but it has no worktree to target, so the lint authorises only control
plane and free paths.

The path itself is computed from this machine's checkout-to-project
mapping and the recorded worktree branch. Shared project rows do not
store checkout paths.

Epic items with sibling-branch task worktrees rely on explicit
``target_kind='epic_task'`` claims (one per task) — see
``.agents/skills/yoke/conduct/engineer-tester-dispatch.md`` for the
per-task acquire / release wiring. An ``item``-only claim authorises
``items.worktree`` and nothing else; the lint exercises the per-task
claims for fan-out coverage.

Codex subagent dispatch runs in-process inside the parent harness
session — the subagent's tool calls land under the parent's
``session_id`` directly, so the parent's own work-claims authorize the
subagent's writes without any per-subagent identity propagation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.project_checkout_locations import (
    epic_task_worktree_path,
    item_worktree_path,
)


@dataclass(frozen=True)
class ClaimedWorktree:
    """One claimed worktree from a session's active work claims.

    ``task_num`` is ``None`` for ``target_kind='item'`` claims and the
    epic task number for ``target_kind='epic_task'`` claims.
    """

    item_id: int
    task_num: Optional[int]
    worktree_path: str


def claimed_worktrees(
    conn: Any, *, session_id: str,
) -> List[ClaimedWorktree]:
    """Return the worktrees this session holds via active ``work_claims``.

    Order is deterministic (claim insertion order). Claims targeting
    ``process`` (no worktree concept) and item / epic-task claims whose
    branch is empty are skipped silently.
    """
    if not session_id:
        return []
    return _claimed_worktrees_for_session(conn, session_id)


def _claimed_worktrees_for_session(
    conn: Any, session_id: str,
) -> List[ClaimedWorktree]:
    """Direct lookup: active ``work_claims`` owned by ``session_id``.

    Skips ``process`` claims (no worktree concept) and item / epic-task
    rows whose branch slug is empty. Returns ``[]`` when the table is
    missing so the lint path degrades safely.
    """
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    try:
        rows = conn.execute(
            "SELECT wc.target_kind, wc.item_id, wc.epic_id, wc.task_num "
            "FROM work_claims wc "
            f"WHERE wc.session_id = {marker} AND wc.released_at IS NULL "
            "ORDER BY wc.id",
            (session_id,),
        ).fetchall()
    except db_backend.operational_error_types(conn):
        return []

    out: List[ClaimedWorktree] = []
    for row in rows:
        kind = row[0] if not hasattr(row, "keys") else row["target_kind"]
        if kind == "item":
            item_id = row[1] if not hasattr(row, "keys") else row["item_id"]
            iid = int(item_id)
            wt = _resolve_item_worktree(conn, iid)
            if wt is not None:
                out.append(
                    ClaimedWorktree(
                        item_id=iid,
                        task_num=None,
                        worktree_path=wt,
                    )
                )
        elif kind == "epic_task":
            epic_id = row[2] if not hasattr(row, "keys") else row["epic_id"]
            task_num = row[3] if not hasattr(row, "keys") else row["task_num"]
            wt = _resolve_epic_task_worktree(
                conn, int(epic_id), int(task_num),
            )
            if wt is not None:
                out.append(
                    ClaimedWorktree(
                        item_id=int(epic_id),
                        task_num=int(task_num),
                        worktree_path=wt,
                    )
                )
        # 'process' target_kind has no worktree concept; skip silently.
    return out


def _resolve_item_worktree(
    conn: Any, item_id: int,
) -> Optional[str]:
    """Compute the machine-local worktree path for an item."""
    try:
        path = item_worktree_path(conn, item_id)
    except db_backend.operational_error_types(conn):
        return None
    return str(path) if path is not None else None


def _resolve_epic_task_worktree(
    conn: Any, epic_id: int, task_num: int,
) -> Optional[str]:
    """Compute the machine-local worktree path for an epic task."""
    try:
        path = epic_task_worktree_path(conn, epic_id, task_num)
    except db_backend.operational_error_types(conn):
        return None
    return str(path) if path is not None else None


__all__ = ["ClaimedWorktree", "claimed_worktrees"]
