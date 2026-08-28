"""Keep launch terminality and its instruction delivery state aligned."""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend


TERMINAL_DELIVERY_STATES = frozenset(
    {"cancelled", "expired", "failed", "outcome_unknown"}
)
#: The complement: a launch in one of these states is still on its way to a
#: session. Named once so the deadline sweep and every reader that asks "which
#: launches are still in flight" cannot drift apart.
IN_FLIGHT_LAUNCH_STATES = frozenset(
    {"queued", "assigned", "launching", "awaiting_registration"}
)
_LAUNCH_CANCELLATION_REASONS = tuple(
    f"launch_{state}" for state in sorted(TERMINAL_DELIVERY_STATES)
)


def _marker(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _value(row: Any, name: str, index: int) -> Any:
    try:
        return row[name]
    except (KeyError, TypeError, IndexError):
        return row[index]


def _launch_message(conn: Any, launch_id: str) -> tuple[str, int] | None:
    marker = _marker(conn)
    row = conn.execute(
        "SELECT message_id, requester_actor_id FROM session_launches "
        f"WHERE launch_id={marker}",
        (launch_id,),
    ).fetchone()
    if row is None:
        return None
    return (
        str(_value(row, "message_id", 0)),
        int(_value(row, "requester_actor_id", 1)),
    )


def close_launch_delivery(
    conn: Any,
    *,
    launch_id: str,
    state: str,
    changed_at: str,
) -> None:
    """Cancel outstanding delivery work for one non-success terminal launch."""
    if state not in TERMINAL_DELIVERY_STATES:
        return
    message = _launch_message(conn, launch_id)
    if message is None:
        return
    message_id, requester_actor_id = message
    marker = _marker(conn)
    reason = f"launch_{state}"
    conn.execute(
        "UPDATE session_message_attempts SET completed_at="
        + marker
        + ", result_code="
        + marker
        + " WHERE message_id="
        + marker
        + " AND completed_at IS NULL",
        (changed_at, reason, message_id),
    )
    conn.execute(
        "UPDATE session_messages SET cancelled_at=COALESCE(cancelled_at,"
        + marker
        + "), cancelled_by_actor_id=COALESCE(cancelled_by_actor_id,"
        + marker
        + "), cancellation_reason=COALESCE(cancellation_reason,"
        + marker
        + ") WHERE message_id="
        + marker,
        (changed_at, requester_actor_id, reason, message_id),
    )
    conn.execute(
        "UPDATE session_message_recipients SET state='cancelled', cancelled_at="
        + marker
        + ", injection_lease_id=NULL, injection_leased_at=NULL, "
        "injection_lease_expires_at=NULL WHERE message_id="
        + marker
        + " AND state IN ('pending','injected')",
        (changed_at, message_id),
    )


def reopen_launch_delivery(conn: Any, *, launch_id: str) -> None:
    """Reopen only delivery work closed by an explicit retry or reconciliation."""
    message = _launch_message(conn, launch_id)
    if message is None:
        return
    message_id, _ = message
    marker = _marker(conn)
    placeholders = ",".join(marker for _ in _LAUNCH_CANCELLATION_REASONS)
    row = conn.execute(
        "SELECT cancellation_reason FROM session_messages WHERE message_id=" + marker,
        (message_id,),
    ).fetchone()
    reason = str(_value(row, "cancellation_reason", 0) or "") if row else ""
    if reason not in _LAUNCH_CANCELLATION_REASONS:
        return
    conn.execute(
        "UPDATE session_messages SET cancelled_at=NULL, cancelled_by_actor_id=NULL, "
        "cancellation_reason=NULL WHERE message_id="
        + marker
        + " AND cancellation_reason IN ("
        + placeholders
        + ")",
        (message_id, *_LAUNCH_CANCELLATION_REASONS),
    )


__all__ = [
    "IN_FLIGHT_LAUNCH_STATES",
    "TERMINAL_DELIVERY_STATES",
    "close_launch_delivery",
    "reopen_launch_delivery",
]
