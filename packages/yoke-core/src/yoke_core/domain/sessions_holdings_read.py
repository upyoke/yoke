"""Session holdings derivation for active work claims and blitz lanes.

Split from :mod:`sessions_list_read` (authored-file line cap). Owns the
per-session grouping the roster read composes into its rows:

* :func:`active_claims_by_session` — active ``work_claims`` rows with
  their rendered targets, worktree lane roles, and the per-claim facts
  from :mod:`sessions_holdings_claim_facts` (an item's coordinates,
  stage and workflow; a steering claim's strategy documents).
* :func:`claimed_blitz_worktree_ids_by_session` — active worker and
  integration worktrees on blitz items each session claims.
* :func:`live_item_claim_holders` — which live session holds each claimed
  item, so a card never shows another session's item as its own work.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from yoke_core.domain import db_backend
from yoke_core.domain.sessions_holdings_claim_rows import active_claim_rows
from yoke_core.domain.work_claim_targets import (
    from_row as work_claim_target_from_row,
    scope_int_sql,
)
from yoke_contracts.item_ref import DEFAULT_PUBLIC_ITEM_PREFIX, format_item_ref
from yoke_contracts.coordination_claim_keys import COORDINATION_TARGET_KINDS
from yoke_core.domain.sessions_holdings_claim_facts import (
    claimed_item_facts,
    clear_failed_read,
    steered_document_slugs,
)
from yoke_core.domain.coordination_claim_keys import key_for_target


def render_claim_target(
    claim: Dict[str, Any],
    item_facts: Dict[int, Dict[str, Any]],
) -> Tuple[str, Dict[str, Any]]:
    """Name one claim's hold, plus the facts that row carries.

    Every kind names itself here — there is no separate label for a reader
    to add, and no path that puts a raw ``target_kind`` in front of an
    operator.
    """
    kind = str(claim.get("target_kind") or "")
    if kind == "item":
        raw_id = claim.get("item_id")
        try:
            item_num = int(raw_id)
        except (TypeError, ValueError):
            return str(raw_id or ""), {}
        found = item_facts.get(item_num)
        if found is not None:
            return str(found["item_ref"]), dict(found)
        fallback = format_item_ref(
            None,
            DEFAULT_PUBLIC_ITEM_PREFIX,
            None,
            item_id=item_num,
        )
        return fallback, {}
    if kind == "epic_task":
        return f"epic {claim.get('epic_id')} task {claim.get('task_num')}", {}
    if kind == "steering":
        steering = work_claim_target_from_row(claim)
        return steering.render(), {
            "scope": dict(steering.scope),
            "project_id": steering.project_id,
        }
    if kind in COORDINATION_TARGET_KINDS:
        # The row of ``work_claims`` the lease projection also reads: naming
        # it by its operator key lets a reader show one hold once, in the
        # words an operator uses to address it.
        key = key_for_target(work_claim_target_from_row(claim))
        return key, {"lease_key": key}
    return f"process {claim.get('process_key') or 'unnamed'}", {}


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
    rows = active_claim_rows(conn)
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
    item_facts = claimed_item_facts(conn, claimed_items)
    doc_slugs = steered_document_slugs(
        conn,
        (
            session_id
            for session_id, claims in raw_by_session.items()
            if any(claim.get("target_kind") == "steering" for claim in claims)
        ),
    )

    grouped: Dict[str, List[Dict[str, Any]]] = {}
    roles: Dict[str, List[Dict[str, Any]]] = {}
    for session_id, claims in raw_by_session.items():
        for claim in claims:
            target, facts = render_claim_target(claim, item_facts)
            if claim.get("target_kind") == "steering":
                # Each steered project pairs with its own documents; one
                # session-level scope can only ever describe one of them.
                key = (session_id, int(facts.get("project_id") or 0))
                facts["strategy_docs"] = doc_slugs.get(key, [])
            grouped.setdefault(session_id, []).append(
                {
                    "target_kind": str(claim.get("target_kind") or ""),
                    "target": target,
                    **facts,
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


def live_item_claim_holders(conn: Any) -> Dict[int, str]:
    """Map each claimed item to the live session holding its work claim.

    A session that merely filed or updated an item must not show it where
    a held item shows, so the roster needs to know who is actually doing
    it. Only a session that has neither ended nor been terminated counts:
    a claim left behind by a session that is gone holds nothing, and the
    reader deserves to see the item as unclaimed rather than as somebody
    else's. Missing tables yield an empty map.
    """
    try:
        rows = conn.execute(
            "SELECT "
            f"{scope_int_sql(conn, 'wc.scope', 'item_id')} AS item_id, "
            "wc.session_id AS session_id "
            "FROM work_claims wc "
            "JOIN harness_sessions hs ON hs.session_id = wc.session_id "
            "WHERE wc.released_at IS NULL AND wc.target_kind = 'item' "
            "AND hs.ended_at IS NULL AND hs.terminated_at IS NULL "
            "ORDER BY wc.claimed_at, wc.id",
        ).fetchall()
    except db_backend.database_error_types(conn):
        clear_failed_read(conn)
        return {}
    holders: Dict[int, str] = {}
    for row in rows:
        item_id = row["item_id"]
        session_id = str(row["session_id"] or "")
        if item_id is None or not session_id:
            continue
        holders.setdefault(int(item_id), session_id)
    return holders


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
            f"JOIN items i ON i.id = {scope_int_sql(conn, 'wc.scope', 'item_id')} "
            f"JOIN item_worktrees iw ON iw.item_id = {scope_int_sql(conn, 'wc.scope', 'item_id')} "
            "AND iw.state = 'active' "
            "WHERE wc.released_at IS NULL AND wc.target_kind = 'item' "
            "AND iw.lane_role IN ('worker', 'integration') "
            "AND LOWER(CAST(i.workflow_id AS TEXT)) = 'blitz' "
            "ORDER BY iw.id",
        ).fetchall()
    except db_backend.database_error_types(conn):
        clear_failed_read(conn)
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
    "claimed_blitz_worktree_ids_by_session",
    "live_item_claim_holders",
    "render_claim_target",
]
