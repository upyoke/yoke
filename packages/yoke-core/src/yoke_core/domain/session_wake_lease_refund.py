"""The retry an unreported relay wake never used.

A wake attempt is charged to its recipient when a relay claims it. When the
relay then goes silent until the lease runs out, nothing proves it started a
native: no resume was accepted, no envelope moved. Expiry closes the attempt
as ``relay_lease_expired``, but the charge stays, and an explicit wake retries
only while no attempt has been charged. One relay outage during a release
therefore used up a live session's explicit wake, and the message waited for
an unrelated hook.

So an attempt that expires with no report gives its charge back, the same way
a declined wake does in ``session_wake_deferral``. The receipt is wakeable
again: the peer-hook broker gets first refusal, as after any failed direct
wake (``session_broker_wake_fallback``), and then the relay claims it with a
fresh lease. An attempt the relay reported on keeps its
charge: a reported resume is settled from the receipt, never retried here.

The refund is bounded per recipient. Past ``MAX_REFUNDED_LEASE_EXPIRIES``
expired attempts the charge stays and the recipient records the
``relay_lease_expired`` escalation, so a relay that never comes back shows by
name in the Fleet report instead of retrying forever.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.session_relay_storage import marker


#: Expired relay wake attempts one recipient may have refunded. Enough to ride
#: out a relay restart during a release; short of an endless loop against a
#: relay that never reports.
MAX_REFUNDED_LEASE_EXPIRIES = 3

LEASE_EXPIRED_RESULT = "relay_lease_expired"


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
    """Give back the charge of an expired, unreported wake, or escalate.

    Call after the expiry is stored, so the count includes it; an attempt a
    late report settled first is left alone. Only a pending recipient with no
    other open wake attempt is touched: a delivered one has nothing left to
    wake, and a newer attempt owns the budget now.
    """
    p = marker(conn)
    attempt = conn.execute(
        "SELECT message_id,target_session_id FROM session_message_attempts "
        f"WHERE attempt_id={p} AND result_code={p}",
        (attempt_id, LEASE_EXPIRED_RESULT),
    ).fetchone()
    if attempt is None:
        return
    message_id, session_id = str(attempt[0]), str(attempt[1])
    expired = conn.execute(
        "SELECT COUNT(*) FROM session_message_attempts "
        f"WHERE message_id={p} AND target_session_id={p} "
        f"AND attempt_kind='wake_relay' AND result_code={p}",
        (message_id, session_id, LEASE_EXPIRED_RESULT),
    ).fetchone()[0]
    if int(expired) <= MAX_REFUNDED_LEASE_EXPIRIES:
        assignment, values = "wake_attempt_count=wake_attempt_count-1", ()
    else:
        assignment, values = "wake_escalation=" + p, (LEASE_EXPIRED_RESULT,)
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
