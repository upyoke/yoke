"""Read-only Fleet message visibility for shared-session child hooks."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from yoke_contracts.session_control.capabilities import capability_for_surface
from yoke_core.domain import db_backend
from yoke_core.domain.session_message_types import row_dict, timestamp, utc_now


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _eligible_hook_event(conn: Any, session_id: str, hook_event: str) -> bool:
    marker = _p(conn)
    row = conn.execute(
        f"SELECT executor_surface FROM harness_sessions WHERE session_id={marker}",
        (session_id,),
    ).fetchone()
    if row is None:
        return False
    capability = capability_for_surface(str(row[0] or ""))
    return capability is not None and hook_event in capability.inject_events


def read_for_hook(
    conn: Any,
    *,
    session_id: str,
    hook_event: str,
    limit: int,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Read deliverable parent receipts without leasing or changing them."""
    if not _eligible_hook_event(conn, session_id, hook_event):
        return []
    marker = _p(conn)
    stamp = timestamp(now or utc_now())
    rows = conn.execute(
        "SELECT r.message_id,m.body,m.sender_actor_id FROM "
        "session_message_recipients r JOIN session_messages m "
        "ON m.message_id=r.message_id "
        f"WHERE r.session_id={marker} AND r.state='pending' "
        "AND m.cancelled_at IS NULL AND m.expires_at>" + marker + " "
        "ORDER BY m.created_at,r.message_id LIMIT " + marker,
        (
            session_id,
            stamp,
            max(1, min(int(limit), 50)),
        ),
    ).fetchall()
    return [row_dict(row) for row in rows]


__all__ = ["read_for_hook"]
