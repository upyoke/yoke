"""Re-present injected messages their recipient never acknowledged.

An injection proves the body reached the model, not that the recipient
answered it; agents routinely act on a body mid-turn and never run the
acknowledgement. Every recipient session, on every harness, gets the reminder
through the same hook lease that delivered the message, on that surface's
manifest ``inject_events``. The backoff keeps it bounded: the first reminder
waits the acknowledgement grace, each later one doubles the wait, capped.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from yoke_contracts.fleet_policy import WAKE_ACK_GRACE_SECONDS
from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import instant_parameter
from yoke_core.domain.session_message_types import parse_timestamp, row_dict


#: Longest wait between two reminders of one unacknowledged message.
REMINDER_MAX_INTERVAL_SECONDS = 3600


def reminder_interval_seconds(injection_count: int) -> int:
    """Wait after the latest injection before the message is re-presented."""
    doublings = min(max(0, int(injection_count) - 1), 16)
    return min(WAKE_ACK_GRACE_SECONDS * 2**doublings, REMINDER_MAX_INTERVAL_SECONDS)


def due_reminder_rows(
    conn: Any,
    *,
    session_id: str,
    now: datetime,
    limit: int,
) -> list[dict[str, Any]]:
    """Injected, unacknowledged receipts whose backoff has elapsed.

    Rows come back in the shape :func:`lease_for_hook` leases, so a
    reminder settles through the ordinary lease completion: that bumps
    ``injection_count`` and ``last_injected_at``, which is what pushes the
    next reminder further out.
    """
    if limit <= 0:
        return []
    postgres = db_backend.connection_is_postgres(conn)
    marker = "%s" if postgres else "?"
    stamp = instant_parameter(conn, now)
    lock = " FOR UPDATE OF r SKIP LOCKED" if postgres else ""
    rows = conn.execute(
        "SELECT r.message_id,r.session_id,r.project_id,r.state,"
        "r.injection_lease_id,r.injection_count,r.last_injected_at,m.body,"
        "m.sender_actor_id,m.sender_session_id,m.sender_surface,m.created_at "
        "FROM session_message_recipients r "
        "JOIN session_messages m ON m.message_id=r.message_id "
        f"WHERE r.session_id={marker} AND r.state='injected' "
        "AND r.acknowledged_at IS NULL AND r.last_injected_at IS NOT NULL "
        f"AND m.cancelled_at IS NULL AND m.expires_at>{marker} "
        "AND (r.injection_lease_id IS NULL "
        f"OR r.injection_lease_expires_at<={marker}) "
        "ORDER BY r.last_injected_at,r.message_id" + lock,
        (session_id, stamp, stamp),
    ).fetchall()
    due: list[dict[str, Any]] = []
    for raw in rows:
        row = row_dict(raw)
        injected_at = parse_timestamp(row.get("last_injected_at"))
        if injected_at is None:
            continue
        waited = (now - injected_at).total_seconds()
        if waited < reminder_interval_seconds(int(row["injection_count"] or 0)):
            continue
        due.append(row)
        if len(due) >= limit:
            break
    return due


__all__ = [
    "REMINDER_MAX_INTERVAL_SECONDS",
    "due_reminder_rows",
    "reminder_interval_seconds",
]
