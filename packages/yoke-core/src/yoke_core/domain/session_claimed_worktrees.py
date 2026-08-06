"""Resolve a harness session's claim-derived worktree authority.

A session's authority to write under a worktree is its **active
work_claims**. This helper is the canonical reader: given a session id,
return the list of ``(item_id, task_num, worktree_path)`` tuples the
session currently owns through ``work_claims``. The session-cwd lint
consumes this set per tool call to decide whether a target path lands
under a claimed worktree, under the main control plane, or under a
free-path allowlist.

The resolution is small (typically 1-3 worktrees + control plane); no
caching is required. Released claims are excluded. Items without an
active recorded lane (e.g. evidence-only items with no worktree)
contribute no row — the session still holds the work claim, but it has
no worktree to target, so the lint authorises only control plane and
free paths.

The path comes from ``item_worktrees.path``, the recorded column,
never from this machine's checkout-to-project mapping. The evaluator is
frequently a *different* machine from the one holding the checkout: an
https control plane relays each hook evaluation to a server that has no
checkout at all, and a mapping lookup there resolves nothing and drops
every claim silently. The recorded column is the only answer that
survives the relay, so authority computed from it is the same on both
sides. ``handlers.claims_work_holders._lane_worktrees`` reads the same
column for the same reason.

Items with worker lanes rely on explicit
``target_kind='epic_task'`` claims (one per task) — see
``.agents/skills/yoke/conduct/engineer-tester-dispatch.md`` for the
per-task acquire / release wiring. An epic-task claim resolves through
its epic, and the lane table keys lanes by item alone, so such a claim
reports every active lane under that epic. This only ever widens what
the caller accepts as its own, so the breadth cannot produce a false
refusal.

Codex subagent dispatch runs in-process inside the parent harness
session — the subagent's tool calls land under the parent's
``session_id`` directly, so the parent's own work-claims authorize the
subagent's writes without any per-subagent identity propagation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from yoke_core.domain import db_backend


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

    Order is deterministic (claim insertion order, then lane id). Claims
    targeting ``process`` (no worktree concept) and claims with no active
    recorded lane are skipped silently.
    """
    if not session_id:
        return []
    return _claimed_worktrees_for_session(conn, session_id)


def _claimed_worktrees_for_session(
    conn: Any, session_id: str,
) -> List[ClaimedWorktree]:
    """Direct lookup: active ``work_claims`` owned by ``session_id``.

    Skips ``process`` claims (no worktree concept). Returns ``[]`` when a
    required table is missing so the lint path degrades safely.
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

    owners: List[Tuple[int, Optional[int]]] = []
    for row in rows:
        kind = row[0] if not hasattr(row, "keys") else row["target_kind"]
        if kind == "item":
            raw = row[1] if not hasattr(row, "keys") else row["item_id"]
            if raw is not None:
                owners.append((int(raw), None))
        elif kind == "epic_task":
            raw = row[2] if not hasattr(row, "keys") else row["epic_id"]
            task = row[3] if not hasattr(row, "keys") else row["task_num"]
            if raw is not None:
                owners.append(
                    (int(raw), int(task) if task is not None else None)
                )
        # 'process' target_kind has no worktree concept; skip silently.

    if not owners:
        return []

    item_lanes = recorded_lane_paths(
        conn, [owner for owner, task in owners if task is None]
    )
    out: List[ClaimedWorktree] = []
    for owner_id, task_num in owners:
        if task_num is None:
            paths = item_lanes.get(owner_id, ())
        else:
            # An epic-task claim authorises its OWN lane, not every lane
            # under the epic: ``epic_tasks.item_worktree_id`` names the
            # one row, and widening to the epic would let one task's
            # session write into a sibling task's worktree.
            paths = _epic_task_lane_paths(conn, owner_id, task_num)
        for path in paths:  # no lane -> contributes nothing
            out.append(
                ClaimedWorktree(
                    item_id=owner_id,
                    task_num=task_num,
                    worktree_path=path,
                )
            )
    return out


def _epic_task_lane_paths(
    conn: Any, epic_id: int, task_num: int,
) -> List[str]:
    """Recorded path of one epic task's own active lane."""
    from yoke_core.domain.schema_common import _table_exists

    if not _table_exists(conn, "epic_tasks"):
        return []
    if not _table_exists(conn, "item_worktrees"):
        return []
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    try:
        rows = conn.execute(
            "SELECT iw.path FROM epic_tasks et "
            "JOIN item_worktrees iw ON iw.id = et.item_worktree_id "
            f"WHERE et.epic_id = {marker} AND et.task_num = {marker} "
            "AND iw.released_at IS NULL "
            "ORDER BY iw.id",
            (int(epic_id), int(task_num)),
        ).fetchall()
    except db_backend.operational_error_types(conn):
        return []
    out: List[str] = []
    for row in rows:
        value = row["path"] if hasattr(row, "keys") else row[0]
        text = str(value or "").strip()
        if text:
            out.append(text)
    return out


#: An item's own lane roles, in the order a claim on the item should
#: prefer them. ``worker`` is deliberately absent: worker lanes belong
#: to an epic's tasks and are stored under the EPIC's ``item_id``, so an
#: item-level claim on an epic would otherwise inherit authority over
#: every one of its tasks' worktrees.
_ITEM_LANE_ROLES = ("integration", "implementation")


def recorded_lane_paths(
    conn: Any, item_ids: Sequence[int],
) -> Dict[int, List[str]]:
    """The lane an item-level claim authorises, per item id.

    Reads ``item_worktrees.path`` directly. Returns at most one lane per
    item — its own — never the worker lanes its epic tasks occupy. A
    schema that carries claims but no lane table (minimal fixtures and
    partially-converged universes both hit this) yields an empty mapping
    rather than failing the caller.
    """
    from yoke_core.domain.schema_common import _table_exists

    wanted = sorted({int(i) for i in item_ids if i is not None})
    if not wanted or not _table_exists(conn, "item_worktrees"):
        return {}
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    placeholders = ", ".join(marker for _ in wanted)
    try:
        found = conn.execute(
            "SELECT item_id, path, lane_role FROM item_worktrees "
            f"WHERE released_at IS NULL AND item_id IN ({placeholders}) "
            "ORDER BY id",
            tuple(wanted),
        ).fetchall()
    except db_backend.operational_error_types(conn):
        return {}

    lanes: Dict[int, List[str]] = {}
    for lane in found:
        has_keys = hasattr(lane, "keys")
        owner = lane["item_id"] if has_keys else lane[0]
        path = str((lane["path"] if has_keys else lane[1]) or "").strip()
        role = str((lane["lane_role"] if has_keys else lane[2]) or "").strip()
        if owner is None or not path or role not in _ITEM_LANE_ROLES:
            continue
        lanes.setdefault(int(owner), []).append(path)
    # One lane per item, matching the single-lane authority an item
    # claim has always carried.
    return {owner: paths[:1] for owner, paths in lanes.items()}


__all__ = ["ClaimedWorktree", "claimed_worktrees", "recorded_lane_paths"]
