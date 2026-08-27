"""Recipient-backed idempotency for explicit native session wakes."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from yoke_contracts.session_control.wake import EXPLICIT_WAKE_ROUTING_FLAG
from yoke_core.domain import db_backend
from yoke_core.domain.session_message_types import parse_timestamp, row_dict, timestamp


def _marker(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _explicit_wake(routing_snapshot: Any) -> bool:
    try:
        snapshot = json.loads(str(routing_snapshot or "{}"))
    except (TypeError, ValueError):
        return False
    return snapshot.get(EXPLICIT_WAKE_ROUTING_FLAG) is True


def recent_wake_blocker(
    conn: Any,
    *,
    session_id: str,
    now: datetime,
    grace_seconds: int,
    exclude_message_id: str | None = None,
    include_queued_explicit: bool = False,
) -> dict[str, Any] | None:
    """Return the receipt that prevents another native wake right now.

    A caller may exclude its deterministic message id so an exact retry can
    deduplicate. New explicit requests also treat an older queued explicit
    receipt as in flight, closing the gap before a relay has claimed it.
    A writer must hold the target harness-session row lock across this read
    and its insert; :func:`request_session_wake` does so.
    """
    marker = _marker(conn)
    rows = conn.execute(
        "SELECT r.message_id,r.state,r.wake_attempt_count,r.last_wake_at,"
        "r.routing_snapshot,m.created_at,EXISTS (SELECT 1 FROM "
        "session_message_attempts a WHERE a.message_id=r.message_id AND "
        "a.target_session_id=r.session_id AND "
        "a.attempt_kind IN ('wake_relay','wake_broker') AND "
        "a.completed_at IS NULL) AS open_attempt "
        "FROM session_message_recipients r JOIN session_messages m "
        "ON m.message_id=r.message_id "
        f"WHERE r.session_id={marker} AND r.state IN ('pending','injected') "
        "AND m.cancelled_at IS NULL AND m.expires_at>"
        + marker
        + " ORDER BY m.created_at,r.message_id",
        (session_id, timestamp(now)),
    ).fetchall()
    grace = timedelta(seconds=max(0, int(grace_seconds)))
    for raw in rows:
        row = row_dict(raw)
        message_id = str(row["message_id"])
        if message_id == exclude_message_id:
            continue
        attempt_count = int(row.get("wake_attempt_count") or 0)
        last_wake = parse_timestamp(row.get("last_wake_at"))
        retry_at = last_wake + grace if last_wake is not None else None
        reason = None
        if bool(row.get("open_attempt")):
            reason = "wake_attempt_in_progress"
        elif attempt_count > 0 and retry_at is not None and retry_at > now:
            reason = "wake_grace_window"
        elif (
            include_queued_explicit
            and attempt_count == 0
            and _explicit_wake(row.get("routing_snapshot"))
        ):
            reason = "wake_queued"
        if reason:
            return {
                "message_id": message_id,
                "wake_attempt_count": attempt_count,
                "last_wake_at": row.get("last_wake_at"),
                "retry_after": timestamp(retry_at) if retry_at else None,
                "reason": reason,
            }
    return None


__all__ = ["recent_wake_blocker"]
