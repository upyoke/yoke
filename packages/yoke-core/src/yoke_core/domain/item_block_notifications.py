"""Address item block-state changes to the accountable item owner."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.decision_request_contract import (
    ITEM_BLOCKED_EVENT,
    ITEM_BLOCK_STATE_CHANGED,
    ITEM_UNBLOCKED_EVENT,
)
from yoke_core.domain.decision_request_events import append_decision_event
from yoke_core.domain.inbox_notifications import fan_out_registered_event
from yoke_core.domain.schema_common import _table_exists


def emit_item_block_state_notification(
    conn: Any,
    *,
    item: Mapping[str, Any],
    blocked: bool,
    session_id: Optional[str] = None,
) -> int:
    """Emit and address one durable block/unblock fact."""
    required = ("actors", "events", "addressed_event_deliveries")
    if not all(_table_exists(conn, table) for table in required):
        return 0
    owner_value = item.get("owner") or item.get("source")
    owner_text = str(owner_value or "")
    owner_actor_id = int(owner_text) if owner_text.isdigit() else None
    if owner_actor_id is not None:
        marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
        owner = conn.execute(
            f"SELECT 1 FROM actors WHERE id = {marker}", (owner_actor_id,),
        ).fetchone()
        if owner is None:
            owner_actor_id = None
    actor_id = None
    if session_id and _table_exists(conn, "harness_sessions"):
        marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
        row = conn.execute(
            f"SELECT actor_id FROM harness_sessions WHERE session_id = {marker}",
            (str(session_id),),
        ).fetchone()
        if row is not None and row[0] is not None:
            actor_id = int(row[0])
    stamp = iso8601_now()
    event_name = ITEM_BLOCKED_EVENT if blocked else ITEM_UNBLOCKED_EVENT
    prefix = item.get("public_item_prefix")
    if not prefix:
        marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
        project = conn.execute(
            f"SELECT public_item_prefix FROM projects WHERE id = {marker}",
            (int(item["project_id"]),),
        ).fetchone()
        prefix = str(project[0]) if project is not None else "YOK"
    sequence = item.get("project_sequence") or item.get("id")
    item_ref = f"{prefix}-{sequence}"
    reason = (
        str(item.get("blocked_reason") or "Item blocked")
        if blocked else "Item unblocked"
    )
    event_id = append_decision_event(
        conn,
        event_name,
        actor_id=actor_id,
        session_id=str(session_id or ""),
        project_id=int(item["project_id"]),
        org_id=None,
        context={
            "item_id": int(item["id"]),
            "item_ref": item_ref,
            "blocked": blocked,
            "reason": reason,
        },
        created_at=stamp,
    )
    inserted = fan_out_registered_event(
        conn,
        event_id=event_id,
        notification_kind=ITEM_BLOCK_STATE_CHANGED,
        event_context={"owner_actor_id": owner_actor_id},
        reason=reason,
        created_at=stamp,
    )
    conn.commit()
    return inserted


def emit_item_block_state_change_if_needed(
    conn: Any,
    *,
    item: Mapping[str, Any],
    field: str,
    value: Any,
    session_id: Optional[str] = None,
) -> int:
    """Normalize a scalar update and emit only for an actual state change."""
    if field != "blocked":
        return 0
    blocked = (
        value if isinstance(value, bool) else str(value).lower() == "true"
    )
    if bool(item.get("blocked")) == blocked:
        return 0
    return emit_item_block_state_notification(
        conn, item=item, blocked=blocked, session_id=session_id,
    )


__all__ = [
    "emit_item_block_state_change_if_needed",
    "emit_item_block_state_notification",
]
