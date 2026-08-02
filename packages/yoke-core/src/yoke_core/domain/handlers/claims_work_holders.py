"""``claims.work.holder.*`` read handlers.

Sibling of :mod:`claims_work` (split for the authored-file line cap).
Read-only claim-holder lookups; the acquire/release mutation handlers
stay in ``claims_work``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class HolderGetRequest(BaseModel):
    item_id: Optional[int] = None


class HolderRow(BaseModel):
    claim_id: int
    session_id: str
    target_kind: str
    item_id: Optional[int] = None
    epic_id: Optional[int] = None
    task_num: Optional[int] = None
    claimed_at: Optional[str] = None
    last_heartbeat: Optional[str] = None
    # Recorded paths of the claim's active worktree lanes. Carried on the
    # holder row so a caller asking "which trees may this session write
    # and verify in?" gets its answer in one round trip instead of a
    # detail fetch per claim.
    lane_worktrees: List[str] = Field(default_factory=list)


class HolderGetResponse(BaseModel):
    holder: Optional[HolderRow] = None


class HolderListRequest(BaseModel):
    item_id: Optional[int] = None
    session_id: Optional[str] = None


class HolderListResponse(BaseModel):
    holders: List[HolderRow] = Field(default_factory=list)


def _err(code: str, message: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message),
    )


def handle_holder_get(request: FunctionCallRequest) -> HandlerOutcome:
    """Look up the active work-claim holder for an item id (read-only)."""
    try:
        body = HolderGetRequest.model_validate(request.payload)
    except Exception as exc:
        return _err("payload_invalid", f"holder.get payload invalid: {exc}")

    item_id = body.item_id
    if item_id is None and request.target.item_id is not None:
        item_id = int(request.target.item_id)
    if item_id is None:
        return _err("payload_invalid", "holder.get requires an item id")

    from yoke_core.domain.sessions_queries_lookup import (
        get_claim_for_work_unit,
    )
    from yoke_core.domain import db_helpers

    with db_helpers.connect() as conn:
        row = get_claim_for_work_unit(conn, item_id=str(int(item_id)))
        holder = _holder_row_to_dict(row) if row else None
        if holder is not None:
            holder["lane_worktrees"] = _lane_worktrees(conn, [holder]).get(
                holder["claim_id"], []
            )

    return HandlerOutcome(result_payload={"holder": holder})


def handle_holder_list(request: FunctionCallRequest) -> HandlerOutcome:
    """List active work-claim holders by item-id or session-id filter."""
    try:
        body = HolderListRequest.model_validate(request.payload)
    except Exception as exc:
        return _err("payload_invalid", f"holder.list payload invalid: {exc}")

    if body.item_id is None and request.target.item_id is not None:
        body.item_id = int(request.target.item_id)
    if body.item_id is None and not body.session_id:
        return _err(
            "payload_invalid",
            "holder.list requires either item_id or session_id",
        )

    from yoke_core.domain import db_backend, db_helpers

    with db_helpers.connect() as conn:
        p = "%s" if db_backend.connection_is_postgres(conn) else "?"
        sql = (
            "SELECT id, session_id, target_kind, item_id, epic_id, task_num, "
            "process_key, conflict_group, claimed_at, last_heartbeat "
            "FROM work_claims WHERE released_at IS NULL"
        )
        params: List[Any] = []
        if body.item_id is not None:
            sql += f" AND target_kind='item' AND item_id = {p}"
            params.append(int(body.item_id))
        if body.session_id:
            sql += f" AND session_id = {p}"
            params.append(body.session_id)
        sql += " ORDER BY claimed_at DESC"
        rows = conn.execute(sql, tuple(params)).fetchall()
        holders = [_holder_row_to_dict(_row_dict(r)) for r in rows]
        lanes = _lane_worktrees(conn, holders)

    for holder in holders:
        holder["lane_worktrees"] = lanes.get(holder["claim_id"], [])
    return HandlerOutcome(result_payload={"holders": holders})


def _lane_worktrees(conn: Any, rows: List[Dict[str, Any]]) -> Dict[int, List[str]]:
    """Recorded paths of each claim's active worktree lanes, by claim id.

    Reads ``item_worktrees.path`` rather than recomputing the path from a
    checkout mapping, because the caller may be a server that holds no
    checkout of its own — the recorded column is the only answer that
    survives the relay.

    An ``epic_task`` claim resolves through its epic, and the lane table
    keys lanes by item alone, so such a claim reports every active lane
    under that epic. The binding check that consumes this only ever
    widens what it accepts, so the breadth cannot produce a false
    refusal.
    """
    from yoke_core.domain import db_backend

    owners = {
        int(row["item_id"] or row["epic_id"]): int(row["claim_id"])
        for row in rows
        if row.get("item_id") or row.get("epic_id")
    }
    if not owners:
        return {}
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    placeholders = ", ".join(p for _ in owners)
    lanes: Dict[int, List[str]] = {}
    found = conn.execute(
        "SELECT item_id, path FROM item_worktrees "
        f"WHERE released_at IS NULL AND item_id IN ({placeholders}) "
        "ORDER BY id",
        tuple(owners),
    ).fetchall()
    for lane in found:
        lane_row = _row_dict(lane)
        owner_id = int(lane_row.get("item_id") or 0)
        path = str(lane_row.get("path") or "").strip()
        claim_id = owners.get(owner_id)
        if claim_id is None or not path:
            continue
        lanes.setdefault(claim_id, []).append(path)
    return lanes


def _row_dict(row: Any) -> Dict[str, Any]:
    if hasattr(row, "keys"):
        return {k: row[k] for k in row.keys()}
    # tuple fallback — caller orders fields manually
    return {}


def _holder_row_to_dict(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    return {
        "claim_id": int(row.get("id") if "id" in row else row.get("claim_id")),
        "session_id": str(row.get("session_id") or ""),
        "target_kind": str(row.get("target_kind") or "item"),
        "item_id": row.get("item_id"),
        "epic_id": row.get("epic_id"),
        "task_num": row.get("task_num"),
        "claimed_at": row.get("claimed_at"),
        "last_heartbeat": row.get("last_heartbeat"),
    }


__all__ = [
    "HolderGetRequest",
    "HolderGetResponse",
    "HolderListRequest",
    "HolderListResponse",
    "HolderRow",
    "handle_holder_get",
    "handle_holder_list",
]
