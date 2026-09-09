"""The retry budget a wake that never started must not spend.

A wake attempt is charged to its recipient at claim time, before the relay
runs anything, because the claim is where two relays are kept off one
envelope. That ordering is right for a wake that goes on to start a native
and wrong for one the machine declines: the recipient walks toward
``max_wake_attempts`` on attempts nothing was ever attempted for, and the
envelope ends up unwakeable for the same reason it was held back. So a
declined wake gives the attempt back.

Backing the recipient off is the other half of the same settlement. A
machine claims one wake job per poll, so a recipient that re-qualifies on
the very next poll takes that single slot for as long as the running turn
lasts, and every other session's wake queues behind a decision that has
already been made.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from yoke_core.domain.session_message_authorization import project_policy
from yoke_core.domain.session_message_types import parse_timestamp, timestamp
from yoke_core.domain.session_relay_storage import marker


def restore_deferred_wake_budget(
    conn: Any,
    *,
    message_id: str,
    session_id: str,
    now: str,
) -> None:
    """Give back the retry a deferred wake never spent, and back it off.

    The claim charges an attempt before the relay runs, so a wake the relay
    declined to start would otherwise walk the recipient toward
    ``max_wake_attempts`` without ever having tried — the message would end
    up unreachable for the same reason it was held back. Nothing was
    started, so the budget is restored.

    Pushing ``wake_after`` forward is the other half. A machine claims one
    wake job per poll, so a recipient that re-qualifies immediately would
    take that single slot every poll for the whole running turn and hold up
    every other session's wake behind it.

    Only a pending recipient is touched, and only while no other wake
    attempt is open against it. One whose envelope has since been delivered
    has nothing left to wake; one already claimed by a newer attempt owns
    the budget and the backoff now, and a deferral arriving late for the
    previous attempt must not take either from it. The caller settles the
    attempt atomically before calling here, so a duplicate report never
    reaches this a second time.
    """
    if not message_id or not session_id:
        return
    p = marker(conn)
    row = conn.execute(
        f"SELECT project_id FROM session_message_recipients WHERE message_id={p} "
        f"AND session_id={p}",
        (message_id, session_id),
    ).fetchone()
    if row is None:
        return
    current = parse_timestamp(now)
    policy = project_policy(conn, int(row[0]))
    backoff = (
        timestamp(current + timedelta(seconds=policy.wake_after_idle_seconds))
        if current is not None
        else now
    )
    conn.execute(
        "UPDATE session_message_recipients SET "
        "wake_attempt_count=wake_attempt_count-1,wake_after=" + p + " "
        f"WHERE message_id={p} AND session_id={p} AND state='pending' "
        f"AND wake_attempt_count>0 AND wake_after<={p} "
        "AND NOT EXISTS (SELECT 1 FROM session_message_attempts a "
        "WHERE a.message_id=session_message_recipients.message_id "
        "AND a.target_session_id=session_message_recipients.session_id "
        "AND a.attempt_kind IN ('wake_relay','wake_broker') "
        "AND a.completed_at IS NULL)",
        (backoff, message_id, session_id, backoff),
    )


__all__ = ["restore_deferred_wake_budget"]
