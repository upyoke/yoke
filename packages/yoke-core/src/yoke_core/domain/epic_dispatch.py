"""Dispatch-chain CRUD and advance logic for epic tasks.

Owns ``dispatch_chain_upsert``, ``dispatch_chain_update``,
``dispatch_chain_refresh_for_activation``, and ``dispatch_chain_advance``.
Re-exported from ``yoke_core.domain.epic`` for patch-target compatibility
so existing ``mock.patch("yoke_core.domain.epic.X")`` fixtures continue
to intercept calls.
"""

from __future__ import annotations

import json
from typing import List

from yoke_core.domain.db_helpers import query_one, query_scalar
from yoke_core.domain.epic_parsing import (
    CHAIN_FIELD_WHITELIST,
    _now_iso,
    _placeholder,
)


def dispatch_chain_upsert(
    conn,
    epic_id: str,
    worktree: str,
    data: dict,
) -> str:
    """Upsert a dispatch chain row from a dict (matching JSON from stdin)."""
    worktree_path = data.get("worktree_path", "")
    queue = data.get("queue", [])
    if isinstance(queue, list):
        queue = json.dumps(queue)
    current_index = data.get("current_index", 0)
    current_task = data.get("current_task", "")
    current_attempt = data.get("current_attempt", 1)
    max_attempts = data.get("max_attempts", 5)
    no_chain = data.get("no_chain", 0)
    started_at = data.get("started_at", "")
    ts = _now_iso()

    p = _placeholder(conn)
    conn.execute(
        f"""INSERT INTO epic_dispatch_chains
           (epic_id, worktree, worktree_path, queue, current_index,
            current_task, current_attempt, max_attempts, no_chain,
            started_at, last_updated)
           VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
           ON CONFLICT(epic_id, worktree) DO UPDATE SET
             worktree_path=excluded.worktree_path,
             queue=excluded.queue,
             current_index=excluded.current_index,
             current_task=excluded.current_task,
             current_attempt=excluded.current_attempt,
             max_attempts=excluded.max_attempts,
             no_chain=excluded.no_chain,
             started_at=excluded.started_at,
             last_updated=excluded.last_updated""",
        (str(epic_id), worktree, worktree_path, queue, current_index,
         current_task, current_attempt, max_attempts, no_chain,
         started_at, ts),
    )
    conn.commit()
    return f"Upserted dispatch chain: {epic_id}/{worktree}"


def dispatch_chain_update(
    conn,
    epic_id: str,
    worktree: str,
    field: str,
    value: str,
) -> str:
    """Update a single field on a dispatch chain."""
    if field not in CHAIN_FIELD_WHITELIST:
        raise ValueError(f"invalid field '{field}' for dispatch-chain-update")

    p = _placeholder(conn)
    count = query_scalar(
        conn,
        f"SELECT COUNT(*) FROM epic_dispatch_chains WHERE epic_id={p} AND worktree={p}",
        (str(epic_id), worktree),
    )
    if count == 0:
        raise LookupError(f"dispatch chain '{epic_id}/{worktree}' not found")

    conn.execute(
        f"UPDATE epic_dispatch_chains SET {field}={p} WHERE epic_id={p} AND worktree={p}",
        (value, str(epic_id), worktree),
    )
    conn.commit()
    return f"Updated {field} of dispatch chain {epic_id}/{worktree} to {value}"


def dispatch_chain_refresh_for_activation(
    conn,
    epic_id: str,
    worktree: str,
    task_num: str,
) -> str:
    """Refresh a chain row at the start of a fresh dispatch.

    Conduct's per-task activation (entry-activation-resolution.md S6f) sets
    ``epic_tasks.status='implementing'`` and persists per-task worktree
    fields, but does not touch ``epic_dispatch_chains``. Without a refresh
    the chain row keeps the prior plan-sync's ``current_attempt`` /
    ``last_updated`` values, which downstream consumers (telemetry,
    scheduler views) misread as yesterday's dispatch.

    This refresh writes ``current_task`` (idempotent if already correct),
    ``current_attempt`` (from ``epic_tasks.dispatch_attempts`` — the honest
    attempt counter conduct has just bumped via ``update_status``), and
    ``last_updated`` (now) in a single transaction.
    """
    p = _placeholder(conn)
    row = query_one(
        conn,
        "SELECT dispatch_attempts FROM epic_tasks "
        f"WHERE epic_id={p} AND task_num={p}",
        (str(epic_id), str(task_num)),
    )
    if row is None:
        raise LookupError(
            f"epic_tasks row '{epic_id}/{task_num}' not found"
        )
    attempt = int(row["dispatch_attempts"] or 1)

    chain_count = query_scalar(
        conn,
        f"SELECT COUNT(*) FROM epic_dispatch_chains WHERE epic_id={p} AND worktree={p}",
        (str(epic_id), worktree),
    )
    if chain_count == 0:
        raise LookupError(
            f"dispatch chain '{epic_id}/{worktree}' not found"
        )

    ts = _now_iso()
    conn.execute(
        "UPDATE epic_dispatch_chains "
        f"SET current_task={p}, current_attempt={p}, last_updated={p} "
        f"WHERE epic_id={p} AND worktree={p}",
        (str(task_num), attempt, ts, str(epic_id), worktree),
    )
    conn.commit()
    return (
        f"Refreshed dispatch chain {epic_id}/{worktree} "
        f"to task {task_num} attempt {attempt}"
    )


def dispatch_chain_advance(conn, epic_id: str, worktree: str) -> str:
    """Advance to next task in dispatch chain.

    Increments current_index and updates current_task.
    Returns ``new_index|next_task``.
    """
    p = _placeholder(conn)
    row = query_one(
        conn,
        f"SELECT current_index, queue FROM epic_dispatch_chains WHERE epic_id={p} AND worktree={p}",
        (str(epic_id), worktree),
    )
    if row is None:
        raise LookupError(f"dispatch chain '{epic_id}/{worktree}' not found")

    cur_index = row["current_index"]
    raw_queue = row["queue"] or ""

    if cur_index is None or (isinstance(cur_index, str) and not cur_index.strip()):
        raise ValueError(f"invalid current_index '<empty>'")

    try:
        cur_index = int(cur_index)
    except (ValueError, TypeError):
        raise ValueError(f"invalid current_index '{cur_index}'")

    if cur_index < 0:
        raise ValueError(f"invalid current_index '{cur_index}'")

    # Parse queue: try JSON array first, fall back to CSV
    queue: List[str] = []
    if raw_queue:
        try:
            parsed = json.loads(raw_queue)
            if isinstance(parsed, list):
                queue = [str(x) for x in parsed]
            elif isinstance(parsed, str):
                queue = [x.strip() for x in parsed.split(",") if x.strip()]
            else:
                queue = [x.strip() for x in raw_queue.split(",") if x.strip()]
        except (json.JSONDecodeError, ValueError):
            queue = [x.strip() for x in raw_queue.split(",") if x.strip()]

    next_index = cur_index + 1
    if next_index >= len(queue):
        raise IndexError(
            f"already at end of queue (current_index={cur_index}, queue_length={len(queue)})"
        )

    next_task = queue[next_index]
    ts = _now_iso()

    conn.execute(
        f"""UPDATE epic_dispatch_chains
           SET current_index={p}, current_task={p}, last_updated={p}
           WHERE epic_id={p} AND worktree={p}""",
        (next_index, next_task, ts, str(epic_id), worktree),
    )
    conn.commit()
    return f"{next_index}|{next_task}"
