"""Session holdings derivation: active work claims and coordination leases.

Split from :mod:`sessions_list_read` (authored-file line cap). Owns the
per-session grouping the roster read composes into its rows:

* :func:`active_claims_by_session` — active ``work_claims`` rows with
  their rendered targets, worktree lane roles, and the per-claim facts
  from :mod:`sessions_holdings_claim_facts` (an item's coordinates,
  stage and workflow; a steering claim's strategy documents).
* :func:`active_leases_by_session` — live shared-operation claim rows
  keyed by holding session (session-owned by typed owner, item-owned
  by whoever currently claims ``owner_item_id``).
* :func:`claimed_blitz_worktree_ids_by_session` — active worker and
  integration worktrees on blitz items each session claims.
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
from yoke_contracts.coordination_claim_keys import (
    COORDINATION_TARGET_KINDS,
)
from yoke_core.domain.sessions_holdings_claim_facts import (
    claimed_item_facts,
    clear_failed_read,
    steered_document_slugs,
)
from yoke_core.domain.coordination_claim_keys import key_for_target
from yoke_core.domain.work_claim_targets import (
    TARGET_KIND_MIGRATION_SERIALIZATION,
    from_row as target_from_row,
)


def _render_target(
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
            target, facts = _render_target(claim, item_facts)
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
    item_facts: Dict[int, Dict[str, Any]],
) -> Dict[str, Any]:
    """Display-shaped claim row, with owning-item identity when item-owned."""
    target = target_from_row(row)
    owner_item_id = (
        target.item_id if target.kind == TARGET_KIND_MIGRATION_SERIALIZATION else None
    )
    payload: Dict[str, Any] = {
        "lease_key": key_for_target(target),
        "acquired_at": row.get("claimed_at"),
        "owner_kind": "item" if owner_item_id is not None else "session",
        "project_id": int(target.project_id or 0),
    }
    if owner_item_id is None:
        return payload
    item_num = int(owner_item_id)
    payload["owner_item_id"] = item_num
    found = item_facts.get(item_num)
    if found is not None:
        payload["owner_item_ref"] = found["item_ref"]
        payload["owner_item_project_id"] = found["item_project_id"]
        payload["owner_item_project_sequence"] = found["item_project_sequence"]
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
    """Group active coordination claims by the session that holds them.

    Session-held rows attach to the holding ``session_id``. Migration
    territory attaches to every session that currently holds an item
    claim on the owning item — the board Claims column uses the same rule
    so a migration hold owned by the claimed item still shows on the
    holding session even after the acquiring session ends. Newest-first,
    one row per ``(session, lease_key)``. Missing table → empty map.
    """
    kinds_sql = ", ".join(f"'{kind}'" for kind in COORDINATION_TARGET_KINDS)
    try:
        rows = conn.execute(
            "SELECT target_kind, scope, session_id, claimed_at "
            f"FROM work_claims WHERE target_kind IN ({kinds_sql}) "
            "AND released_at IS NULL "
            "ORDER BY claimed_at DESC, id DESC",
        ).fetchall()
    except db_backend.database_error_types(conn):
        clear_failed_read(conn)
        return {}
    item_sessions = _item_claim_sessions(roles_by_session or {})
    owner_ids = [
        item_id
        for item_id in (
            target_from_row(row).item_id
            if str(row["target_kind"]) == TARGET_KIND_MIGRATION_SERIALIZATION
            else None
            for row in rows
        )
        if item_id is not None
    ]
    item_facts = claimed_item_facts(conn, owner_ids)
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    seen: set[tuple[str, str]] = set()
    for row in rows:
        payload = _lease_payload(dict(row), item_facts)
        if not payload["lease_key"]:
            continue
        if payload["owner_kind"] == "item":
            owner_item_id = payload.get("owner_item_id")
            if owner_item_id is None:
                continue
            for holder in item_sessions.get(int(owner_item_id), []):
                _attach_lease(grouped, seen, holder, payload)
            continue
        _attach_lease(grouped, seen, str(row["session_id"] or ""), payload)
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
    "active_leases_by_session",
    "claimed_blitz_worktree_ids_by_session",
]
