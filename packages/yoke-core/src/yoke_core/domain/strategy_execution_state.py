"""Read model for Blitz execution links and strategy-document claims."""

from __future__ import annotations

from typing import Any, Optional

from yoke_contracts.item_ref import format_item_ref
from yoke_core.domain import db_backend


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
    row = _row(
        conn.execute(
            "SELECT i.id, i.project_id, i.title, i.status, i.workflow_id, "
            "i.workflow_version_id, i.owner, i.source, i.created_at, "
            "i.workflow_posture, p.slug AS project_slug, "
            "p.name AS project_name "
            "FROM items i JOIN projects p ON p.id = i.project_id "
            f"WHERE i.id = {marker}",
            (int(item_id),),
        )
    )
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
    return _row(
        conn.execute(
            "SELECT wc.id, wc.session_id, wc.claimed_at, "
            "hs.executor_surface, hs.executor "
            "FROM work_claims wc "
            "LEFT JOIN harness_sessions hs ON hs.session_id = wc.session_id "
            "WHERE wc.target_kind = 'item' "
            f"AND wc.item_id = {marker} AND wc.released_at IS NULL "
            "ORDER BY wc.claimed_at DESC LIMIT 1",
            (int(item_id),),
        )
    )


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
    claim = _row(
        conn.execute(
            "SELECT c.id, c.project_id, c.strategy_doc_slug, "
            "c.owning_item_id, c.registered_by_actor_id, "
            "c.registered_by_session_id, c.registered_at, "
            "i.title AS item_title, i.status AS item_status, "
            "i.workflow_id, i.workflow_version_id, "
            "v.version AS workflow_version, "
            "i.project_sequence, p.slug AS project_slug, "
            "p.public_item_prefix "
            "FROM strategy_doc_claims c "
            "JOIN items i ON i.id = c.owning_item_id "
            "JOIN workflow_versions v ON v.id = i.workflow_version_id "
            "JOIN projects p ON p.id = i.project_id "
            f"WHERE {where} AND c.released_at IS NULL",
            params,
        )
    )
    if claim is not None:
        claim["item_ref"] = format_item_ref(
            claim["project_slug"],
            claim["public_item_prefix"],
            int(claim["project_sequence"]),
        )
    return claim


__all__ = [
    "StrategyDocClaimAuthorizationError",
    "StrategyDocClaimConflictError",
    "StrategyExecutionError",
    "StrategyExecutionLinkError",
    "active_strategy_doc_claim",
]
