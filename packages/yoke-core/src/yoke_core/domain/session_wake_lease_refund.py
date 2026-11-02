"""Refund wake charges when relay or broker loss proves no native turn began.

Relay lease expiry and abandoned broker reservations share one bounded refund
budget per recipient. Reported native outcomes keep their charge. Beyond the
refund limit, the attempt's own loss code escalates through the existing wake
failure notice instead of retrying forever.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.session_relay_storage import marker


#: Unreported relay and broker losses one recipient may have refunded.
MAX_REFUNDED_LEASE_EXPIRIES = 3

LEASE_EXPIRED_RESULT = "relay_lease_expired"

_UNREPORTED_LOSS_MATCH = (
    "((attempt_kind='wake_relay' AND result_code='relay_lease_expired') "
    "OR (attempt_kind='wake_broker' AND result_code IN "
    "('broker_hook_lease_expired','broker_lost','broker_timeout')))"
)


def unreported_expiring_wakes(conn: Any, *, cutoff: object) -> list[str]:
    """Relay wake attempts that will expire with no report at all."""
    p = marker(conn)
    rows = conn.execute(
        "SELECT attempt_id FROM session_message_attempts "
        "WHERE attempt_kind='wake_relay' AND completed_at IS NULL "
        f"AND result_code IS NULL AND started_at<={p} ORDER BY started_at,attempt_id",
        (cutoff,),
    ).fetchall()
    return [str(row[0]) for row in rows]


def refund_unreported_wake(conn: Any, *, attempt_id: str) -> None:
    """Give back the charge of a closed, unreported wake loss, or escalate.

    Call after the loss is stored, so the count includes it; an attempt a
    late report settled first is left alone. Only a pending recipient with no
    other open wake attempt is touched: a delivered one has nothing left to
    wake, and a newer attempt owns the budget now.
    """
    p = marker(conn)
    attempt = conn.execute(
        "SELECT message_id,target_session_id,result_code FROM session_message_attempts "
        f"WHERE attempt_id={p} AND completed_at IS NOT NULL AND "
        + _UNREPORTED_LOSS_MATCH,
        (attempt_id,),
    ).fetchone()
    if attempt is None:
        return
    message_id, session_id = str(attempt[0]), str(attempt[1])
    expired = conn.execute(
        "SELECT COUNT(*) FROM session_message_attempts "
        f"WHERE message_id={p} AND target_session_id={p} "
        "AND completed_at IS NOT NULL AND " + _UNREPORTED_LOSS_MATCH,
        (message_id, session_id),
    ).fetchone()[0]
    if int(expired) <= MAX_REFUNDED_LEASE_EXPIRIES:
        assignment, values = "wake_attempt_count=wake_attempt_count-1", ()
    else:
        assignment, values = "wake_escalation=" + p, (str(attempt[2]),)
    conn.execute(
        "UPDATE session_message_recipients SET " + assignment + " "
        f"WHERE message_id={p} AND session_id={p} AND state='pending' "
        "AND wake_attempt_count>0 "
        "AND NOT EXISTS (SELECT 1 FROM session_message_attempts a "
        "WHERE a.message_id=session_message_recipients.message_id "
        "AND a.target_session_id=session_message_recipients.session_id "
        "AND a.attempt_kind IN ('wake_relay','wake_broker') "
        "AND a.completed_at IS NULL)",
        (*values, message_id, session_id),
    )


__all__ = [
    "LEASE_EXPIRED_RESULT",
    "MAX_REFUNDED_LEASE_EXPIRIES",
    "refund_unreported_wake",
    "unreported_expiring_wakes",
]
