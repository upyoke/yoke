"""Document ancestry, Blitz execution links, and item-owned claims."""

from __future__ import annotations

from typing import Any, Optional

from yoke_contracts.item_ref import format_item_ref
from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.strategy_docs import (
    get_doc,
)


class StrategyExecutionError(RuntimeError):
    """Base for refused document-execution operations."""


class StrategyExecutionLinkError(StrategyExecutionError):
    """Raised for an invalid item-to-document execution relationship."""


class StrategyDocClaimConflictError(StrategyExecutionError):
    """Raised when another item owns the active document claim."""


class StrategyDocClaimAuthorizationError(StrategyExecutionError):
    """Raised when a session may not revise a claimed execution document."""


def _marker(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _row(cursor: Any) -> Optional[dict[str, Any]]:
    value = cursor.fetchone()
    if value is None:
        return None
    if hasattr(value, "keys"):
        return dict(value)
    columns = [str(column[0]) for column in cursor.description]
    return dict(zip(columns, value))


def _item_row(conn: Any, item_id: int) -> dict[str, Any]:
    marker = _marker(conn)
    row = _row(conn.execute(
        "SELECT i.id, i.project_id, i.title, i.status, i.workflow_id, "
        "i.workflow_version_id, i.owner, i.source, i.created_at, "
        "i.workflow_posture, p.slug AS project_slug, p.name AS project_name "
        "FROM items i JOIN projects p ON p.id = i.project_id "
        f"WHERE i.id = {marker}",
        (int(item_id),),
    ))
    if row is None:
        raise StrategyExecutionLinkError(f"item {item_id} does not exist")
    return row


def _require_blitz_item(conn: Any, item_id: int) -> dict[str, Any]:
    item = _item_row(conn, item_id)
    if str(item["workflow_id"]) != "blitz":
        raise StrategyExecutionLinkError(
            f"item {item_id} uses workflow {item['workflow_id']!r}; "
            "only Blitz items link execution strategy documents"
        )
    return item


def _active_item_claim(
    conn: Any,
    item_id: int,
) -> Optional[dict[str, Any]]:
    marker = _marker(conn)
    return _row(conn.execute(
        "SELECT wc.id, wc.session_id, wc.claimed_at, "
        "hs.executor_display_name, hs.executor "
        "FROM work_claims wc "
        "LEFT JOIN harness_sessions hs ON hs.session_id = wc.session_id "
        "WHERE wc.target_kind = 'item' "
        f"AND wc.item_id = {marker} AND wc.released_at IS NULL "
        "ORDER BY wc.claimed_at DESC LIMIT 1",
        (int(item_id),),
    ))


def link_execution_document(
    conn: Any,
    *,
    item_id: int,
    project_id: int,
    slug: str,
    actor_id: Optional[int],
    session_id: Optional[str],
) -> dict[str, Any]:
    """Link exactly one execution document to one Blitz item."""
    item = _require_blitz_item(conn, item_id)
    if int(item["project_id"]) != int(project_id):
        raise StrategyExecutionLinkError(
            "the execution document must belong to the Blitz project"
        )
    get_doc(conn, int(project_id), slug)
    marker = _marker(conn)
    active = active_strategy_doc_claim(conn, item_id=int(item_id))
    if active is not None and str(active["strategy_doc_slug"]) != slug:
        raise StrategyExecutionLinkError(
            "an active Blitz cannot replace its claimed execution document"
        )
    linked_at = iso8601_now()
    conn.execute(
        "INSERT INTO item_strategy_docs "
        "(item_id, project_id, strategy_doc_slug, linked_by_actor_id, "
        "linked_by_session_id, linked_at) "
        f"VALUES ({', '.join(marker for _ in range(6))}) "
        "ON CONFLICT(item_id) DO UPDATE SET "
        "project_id = EXCLUDED.project_id, "
        "strategy_doc_slug = EXCLUDED.strategy_doc_slug, "
        "linked_by_actor_id = EXCLUDED.linked_by_actor_id, "
        "linked_by_session_id = EXCLUDED.linked_by_session_id, "
        "linked_at = EXCLUDED.linked_at",
        (
            int(item_id), int(project_id), slug, actor_id, session_id, linked_at,
        ),
    )
    conn.commit()
    return {
        "item_id": int(item_id),
        "project_id": int(project_id),
        "slug": slug,
        "linked_at": linked_at,
    }


def active_strategy_doc_claim(
    conn: Any,
    *,
    project_id: Optional[int] = None,
    slug: Optional[str] = None,
    item_id: Optional[int] = None,
) -> Optional[dict[str, Any]]:
    """Return one active item-owned document claim by document or item."""
    marker = _marker(conn)
    if item_id is not None:
        where, params = f"c.owning_item_id = {marker}", (int(item_id),)
    elif project_id is not None and slug is not None:
        where = f"c.project_id = {marker} AND c.strategy_doc_slug = {marker}"
        params = (int(project_id), slug)
    else:
        raise ValueError("document identity or item_id is required")
    claim = _row(conn.execute(
        "SELECT c.id, c.project_id, c.strategy_doc_slug, c.owning_item_id, "
        "c.registered_by_actor_id, c.registered_by_session_id, "
        "c.registered_at, i.title AS item_title, i.status AS item_status, "
        "i.project_sequence, p.slug AS project_slug, p.public_item_prefix "
        "FROM strategy_doc_claims c "
        "JOIN items i ON i.id = c.owning_item_id "
        "JOIN projects p ON p.id = i.project_id "
        f"WHERE {where} AND c.released_at IS NULL",
        params,
    ))
    if claim is not None:
        claim["item_ref"] = format_item_ref(
            claim["project_slug"],
            claim["public_item_prefix"],
            claim["project_sequence"],
            item_id=int(claim["owning_item_id"]),
        )
    return claim


def acquire_strategy_doc_claim(
    conn: Any,
    *,
    item_id: int,
    session_id: str,
    actor_id: Optional[int],
) -> dict[str, Any]:
    """Atomically acquire the linked document for the active Blitz item."""
    _require_blitz_item(conn, item_id)
    item_claim = _active_item_claim(conn, item_id)
    if item_claim is None or str(item_claim["session_id"]) != session_id:
        raise StrategyDocClaimAuthorizationError(
            f"session {session_id!r} does not hold item {item_id}'s active claim"
        )
    marker = _marker(conn)
    link = _row(conn.execute(
        "SELECT project_id, strategy_doc_slug FROM item_strategy_docs "
        f"WHERE item_id = {marker}",
        (int(item_id),),
    ))
    if link is None:
        raise StrategyExecutionLinkError(
            f"Blitz item {item_id} has no execution document"
        )
    registered_at = iso8601_now()
    inserted = _row(conn.execute(
        "INSERT INTO strategy_doc_claims "
        "(project_id, strategy_doc_slug, owning_item_id, "
        "registered_by_actor_id, registered_by_session_id, registered_at) "
        f"VALUES ({', '.join(marker for _ in range(6))}) "
        "ON CONFLICT DO NOTHING RETURNING id",
        (
            int(link["project_id"]),
            str(link["strategy_doc_slug"]),
            int(item_id),
            actor_id,
            session_id,
            registered_at,
        ),
    ))
    if inserted is None:
        holder = active_strategy_doc_claim(
            conn,
            project_id=int(link["project_id"]),
            slug=str(link["strategy_doc_slug"]),
        )
        if holder is not None and int(holder["owning_item_id"]) == int(item_id):
            return holder
        label = (
            f"item {holder['owning_item_id']} ({holder['item_title']})"
            if holder is not None else "another active item"
        )
        raise StrategyDocClaimConflictError(
            f"strategy document {link['strategy_doc_slug']!r} is owned by {label}"
        )
    conn.commit()
    return active_strategy_doc_claim(conn, item_id=int(item_id)) or {}


def authorize_strategy_doc_write(
    conn: Any,
    *,
    project_id: int,
    slug: str,
    session_id: str,
) -> bool:
    """Authorize a claimed doc write; return False when no claim exists.

    A False result tells the caller to apply its ordinary process-claim
    boundary. An active execution claim replaces that boundary: only the
    session currently holding the owning Blitz's item claim may revise it.
    """
    claim = active_strategy_doc_claim(
        conn, project_id=int(project_id), slug=slug,
    )
    if claim is None:
        return False
    item_claim = _active_item_claim(conn, int(claim["owning_item_id"]))
    if item_claim is None or str(item_claim["session_id"]) != session_id:
        raise StrategyDocClaimAuthorizationError(
            f"strategy document {slug!r} is owned by Blitz item "
            f"{claim['owning_item_id']}; only the session holding that "
            "item's active claim may revise it"
        )
    return True


def release_strategy_doc_claim(
    conn: Any,
    *,
    item_id: int,
    session_id: str,
    actor_id: Optional[int],
    break_glass: bool = False,
    reason: Optional[str] = None,
) -> dict[str, Any]:
    """Release an active item-owned claim, recording break-glass rationale."""
    claim = active_strategy_doc_claim(conn, item_id=int(item_id))
    if claim is None:
        raise StrategyExecutionLinkError(
            f"item {item_id} has no active strategy-document claim"
        )
    if break_glass:
        if not str(reason or "").strip():
            raise StrategyDocClaimAuthorizationError(
                "break-glass release requires a durable reason"
            )
    else:
        item_claim = _active_item_claim(conn, item_id)
        if item_claim is None or str(item_claim["session_id"]) != session_id:
            raise StrategyDocClaimAuthorizationError(
                "normal release requires the session holding the item claim"
            )
    released_at = iso8601_now()
    marker = _marker(conn)
    conn.execute(
        "UPDATE strategy_doc_claims "
        f"SET released_by_actor_id = {marker}, "
        f"released_by_session_id = {marker}, released_at = {marker}, "
        f"release_mode = {marker}, release_reason = {marker} "
        f"WHERE id = {marker} AND released_at IS NULL",
        (
            actor_id,
            session_id,
            released_at,
            "break_glass" if break_glass else "normal",
            str(reason or "lifecycle release"),
            int(claim["id"]),
        ),
    )
    conn.commit()
    return {
        "claim_id": int(claim["id"]),
        "item_id": int(item_id),
        "slug": str(claim["strategy_doc_slug"]),
        "released_at": released_at,
        "release_mode": "break_glass" if break_glass else "normal",
    }


__all__ = [
    "StrategyDocClaimAuthorizationError",
    "StrategyDocClaimConflictError",
    "StrategyExecutionError",
    "StrategyExecutionLinkError",
    "acquire_strategy_doc_claim",
    "active_strategy_doc_claim",
    "authorize_strategy_doc_write",
    "link_execution_document",
    "release_strategy_doc_claim",
]
