"""Session holdings derivation: active work claims and coordination leases.

Split from :mod:`sessions_list_read` (authored-file line cap). Owns the
per-session grouping the roster read composes into its rows:

* :func:`active_claims_by_session` — active ``work_claims`` rows with
  their rendered targets, worktree lane roles, and per-item public
  drill-in coordinates resolved in one batched read.
* :func:`active_leases_by_session` — live ``coordination_leases`` rows
  keyed by holding session (session-owned by typed owner, item-owned
  by whoever currently claims ``owner_item_id``).
* :func:`claimed_blitz_worktree_ids_by_session` — active worker and
  integration worktrees on blitz items each session claims.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from yoke_core.domain import db_backend
from yoke_core.domain.work_claim_targets import from_row as work_claim_target_from_row
from yoke_contracts.item_ref import DEFAULT_PUBLIC_ITEM_PREFIX, format_item_ref

_CLAIM_ROWS_SQL = (
    "SELECT wc.session_id, wc.target_kind, wc.item_id, wc.epic_id, "
    "wc.task_num, wc.process_key, wc.conflict_group, wc.claimed_at, "
    "wc.steering_project_id, wc.steering_strategy_doc_slugs, "
    "wc.reason, COALESCE(task_lane.lane_role, item_lane.lane_role) "
    "AS lane_role "
    "FROM work_claims wc "
    "LEFT JOIN epic_tasks et ON wc.target_kind = 'epic_task' "
    "AND et.epic_id = wc.epic_id AND et.task_num = wc.task_num "
    "LEFT JOIN item_worktrees task_lane "
    "ON task_lane.id = et.item_worktree_id "
    "AND task_lane.state = 'active' "
    "LEFT JOIN item_worktrees item_lane ON item_lane.id = ("
    "SELECT iw.id FROM item_worktrees iw "
    "WHERE wc.target_kind = 'item' AND iw.item_id = wc.item_id "
    "AND iw.state = 'active' "
    "ORDER BY CASE iw.lane_role WHEN 'integration' THEN 0 "
    "WHEN 'implementation' THEN 1 ELSE 2 END, iw.id LIMIT 1"
    ") "
    "WHERE wc.released_at IS NULL ORDER BY wc.claimed_at ASC"
)


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _empty_on_missing_relation(conn: Any) -> None:
    """Clear an aborted transaction after a missing-relation read."""
    try:
        conn.rollback()
    except Exception:
        pass


def claim_item_coordinates(
    conn: Any,
    item_ids: List[int],
) -> Dict[int, Dict[str, Any]]:
    """Map internal item ids to public identity facts in one read.

    Returns ``{item_id: {"ref", "project_id", "project_sequence"}}``;
    ids with no backing item row are absent so callers can apply the
    same fallback :func:`display_claim_item_id` uses.
    """
    distinct: List[int] = []
    seen: set[int] = set()
    for value in item_ids:
        try:
            number = int(value)
        except (TypeError, ValueError):
            continue
        if number not in seen:
            seen.add(number)
            distinct.append(number)
    if not distinct:
        return {}
    marker = _p(conn)
    placeholders = ", ".join(marker for _ in distinct)
    try:
        rows = conn.execute(
            "SELECT i.id AS id, i.project_id AS project_id, "
            "i.project_sequence AS project_sequence, "
            "p.public_item_prefix AS public_item_prefix "
            "FROM items i JOIN projects p ON p.id = i.project_id "
            f"WHERE i.id IN ({placeholders})",
            tuple(distinct),
        ).fetchall()
    except db_backend.database_error_types(conn):
        _empty_on_missing_relation(conn)
        return {}
    coordinates: Dict[int, Dict[str, Any]] = {}
    for row in rows:
        coordinates[int(row["id"])] = {
            "ref": format_item_ref(
                None,
                row["public_item_prefix"],
                row["project_sequence"],
            ),
            "project_id": int(row["project_id"]),
            "project_sequence": int(row["project_sequence"]),
        }
    return coordinates


def _render_target(
    claim: Dict[str, Any],
    coordinates: Dict[int, Dict[str, Any]],
) -> Tuple[str, Dict[str, Any]]:
    """Render one claim's display target plus its drill-in coordinates."""
    kind = str(claim.get("target_kind") or "")
    if kind == "item":
        raw_id = claim.get("item_id")
        try:
            item_num = int(raw_id)
        except (TypeError, ValueError):
            return str(raw_id or ""), {}
        found = coordinates.get(item_num)
        if found is not None:
            return str(found["ref"]), {
                "item_ref": found["ref"],
                "item_project_id": found["project_id"],
                "item_project_sequence": found["project_sequence"],
            }
        fallback_ref = format_item_ref(
            None, DEFAULT_PUBLIC_ITEM_PREFIX, None, item_id=item_num,
        )
        return fallback_ref, {}
    if kind == "epic_task":
        return f"epic {claim.get('epic_id')} task {claim.get('task_num')}", {}
    if kind == "steering_scope":
        steering = work_claim_target_from_row(claim)
        return steering.render(), {
            "steering_project_id": steering.steering_project_id,
            "steering_strategy_doc_slugs": list(
                steering.steering_strategy_doc_slugs or ()
            ),
        }
    return str(claim.get("process_key") or ""), {}


def active_claims_by_session(
    conn: Any,
) -> Tuple[
    Dict[str, List[Dict[str, Any]]],
    Dict[str, List[Dict[str, Any]]],
]:
    """Group active work claims by session.

    Returns ``(claims_by_session, roles_by_session)``. The first map is
    display-shaped (rendered target, reason, per-item drill-in
    coordinates); the second carries the raw item ids and worktree lane
    roles used for focus/role matching. Item-target refs resolve through
    one batched identity read rather than a query per claim.
    """
    rows = conn.execute(_CLAIM_ROWS_SQL).fetchall()
    raw_by_session: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        claim = dict(row)
        raw_by_session.setdefault(str(claim["session_id"]), []).append(claim)

    claimed_items = [
        int(claim["item_id"])
        for claims in raw_by_session.values()
        for claim in claims
        if claim.get("target_kind") == "item" and claim["item_id"] is not None
    ]
    coordinates = claim_item_coordinates(conn, claimed_items)

    grouped: Dict[str, List[Dict[str, Any]]] = {}
    roles: Dict[str, List[Dict[str, Any]]] = {}
    for session_id, claims in raw_by_session.items():
        for claim in claims:
            target, coords = _render_target(claim, coordinates)
            grouped.setdefault(session_id, []).append(
                {
                    "target_kind": str(claim.get("target_kind") or ""),
                    "target": target,
                    **coords,
                    "claimed_at": claim.get("claimed_at"),
                    "reason": claim.get("reason"),
                }
            )
            claimed_item = (
                claim.get("item_id")
                if claim.get("target_kind") == "item"
                else claim.get("epic_id")
            )
            roles.setdefault(session_id, []).append(
                {
                    "target_kind": str(claim.get("target_kind") or ""),
                    "item_id": (
                        int(claimed_item) if claimed_item is not None else None
                    ),
                    "lane_role": claim.get("lane_role"),
                    "claimed_at": claim.get("claimed_at"),
                }
            )
    return grouped, roles


def _item_claim_sessions(
    roles_by_session: Dict[str, List[Dict[str, Any]]],
) -> Dict[int, List[str]]:
    """Map claimed item ids to the sessions that currently hold them."""
    mapping: Dict[int, List[str]] = {}
    for session_id, roles in roles_by_session.items():
        for role in roles:
            if role.get("target_kind") != "item" or role.get("item_id") is None:
                continue
            mapping.setdefault(int(role["item_id"]), []).append(session_id)
    return mapping


def _lease_payload(
    row: Dict[str, Any],
    coordinates: Dict[int, Dict[str, Any]],
) -> Dict[str, Any]:
    """Display-shaped lease row, with owning-item identity when item-owned."""
    owner_kind = str(row.get("owner_kind") or "session")
    payload: Dict[str, Any] = {
        "lease_key": str(row["lease_key"] or ""),
        "acquired_at": row.get("acquired_at"),
        "owner_kind": owner_kind,
        "project_id": int(row["project_id"]),
    }
    owner_item_id = row.get("owner_item_id")
    if owner_kind != "item" or owner_item_id is None:
        return payload
    item_num = int(owner_item_id)
    payload["owner_item_id"] = item_num
    found = coordinates.get(item_num)
    if found is not None:
        payload["owner_item_ref"] = found["ref"]
        payload["owner_item_project_id"] = found["project_id"]
        payload["owner_item_project_sequence"] = found["project_sequence"]
    return payload


def _attach_lease(
    grouped: Dict[str, List[Dict[str, Any]]],
    seen: set[tuple[str, str]],
    holder: str,
    payload: Dict[str, Any],
) -> None:
    """Append ``payload`` to ``holder`` unless this lease_key is already there."""
    lease_key = str(payload.get("lease_key") or "")
    if not holder or not lease_key:
        return
    dedup_key = (holder, lease_key)
    if dedup_key in seen:
        return
    seen.add(dedup_key)
    grouped.setdefault(holder, []).append(dict(payload))


def active_leases_by_session(
    conn: Any,
    roles_by_session: Dict[str, List[Dict[str, Any]]] | None = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """Group active coordination leases by the session that holds them.

    Session-owned rows attach to ``owner_session_id`` (else acquire-time
    ``session_id``). Item-owned rows attach to every session that currently
    holds an item claim on ``owner_item_id`` — the board Claims column
    uses the same rule so a migration lease owned by the claimed item
    still shows on the holding session. Newest-first, one row per
    ``(session, lease_key)``. Missing table → empty map.
    """
    try:
        rows = conn.execute(
            "SELECT project_id, lease_key, session_id, acquired_at, "
            "owner_kind, owner_session_id, owner_item_id "
            "FROM coordination_leases WHERE released_at IS NULL "
            "ORDER BY acquired_at DESC, id DESC",
        ).fetchall()
    except db_backend.database_error_types(conn):
        _empty_on_missing_relation(conn)
        return {}
    item_sessions = _item_claim_sessions(roles_by_session or {})
    owner_ids = [
        int(row["owner_item_id"])
        for row in rows
        if str(row["owner_kind"] or "") == "item" and row["owner_item_id"] is not None
    ]
    coordinates = claim_item_coordinates(conn, owner_ids)
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    seen: set[tuple[str, str]] = set()
    for row in rows:
        payload = _lease_payload(dict(row), coordinates)
        if not payload["lease_key"]:
            continue
        if payload["owner_kind"] == "item":
            owner_item_id = payload.get("owner_item_id")
            if owner_item_id is None:
                continue
            for holder in item_sessions.get(int(owner_item_id), []):
                _attach_lease(grouped, seen, holder, payload)
            continue
        holder = str(row["owner_session_id"] or row["session_id"] or "")
        _attach_lease(grouped, seen, holder, payload)
    return grouped


def claimed_blitz_worktree_ids_by_session(
    conn: Any,
) -> Dict[str, List[int]]:
    """Active worker/integration worktrees on blitz items each session claims.

    The Sessions page counts these ids (unique across the roster), not
    sessions whose focus happens to name a blitz item. Missing tables
    yield an empty map.
    """
    try:
        rows = conn.execute(
            "SELECT wc.session_id AS session_id, iw.id AS worktree_id "
            "FROM work_claims wc "
            "JOIN items i ON i.id = wc.item_id "
            "JOIN item_worktrees iw ON iw.item_id = wc.item_id "
            "AND iw.state = 'active' "
            "WHERE wc.released_at IS NULL AND wc.target_kind = 'item' "
            "AND iw.lane_role IN ('worker', 'integration') "
            "AND LOWER(CAST(i.workflow_id AS TEXT)) = 'blitz' "
            "ORDER BY iw.id",
        ).fetchall()
    except db_backend.database_error_types(conn):
        _empty_on_missing_relation(conn)
        return {}
    grouped: Dict[str, List[int]] = {}
    seen: set[tuple[str, int]] = set()
    for row in rows:
        session_id = str(row["session_id"] or "")
        worktree_id = int(row["worktree_id"])
        key = (session_id, worktree_id)
        if not session_id or key in seen:
            continue
        seen.add(key)
        grouped.setdefault(session_id, []).append(worktree_id)
    return grouped


__all__ = [
    "active_claims_by_session",
    "active_leases_by_session",
    "claim_item_coordinates",
    "claimed_blitz_worktree_ids_by_session",
]
