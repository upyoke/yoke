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

Giving the attempt back forever is the failure that hides. A deferral costs
nothing and restores everything, so the loop has no end: one session was
declined fourteen times in seventeen minutes and another four times in three,
each at ``wake_attempt_count`` zero, because the native holding custody had
finished its work and never exited. Nothing accumulated, so nothing was ever
reportable, and only a person killing the process ended it.

So the restore is bounded, per holding process. Past ``MAX_RESTORED_DEFERRALS``
declines naming one pid the attempt is
allowed to count, and the recipient walks to ``max_wake_attempts`` and stops
being re-claimed every poll. Nothing is lost by that and nothing is killed:
if the turn really is running, its next tool call runs the hook that attaches
the envelope, which is the cheap route this whole path exists to fall back
from. What changes is that a recipient no route is reaching stops consuming a
wake slot every minute and becomes a row the seat can act on, rather than an
invisible loop that resets itself forever.
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

from yoke_contracts.session_control.wake_delivery import NATIVE_TURN_RUNNING_RESULT
from yoke_core.domain.session_message_authorization import project_policy
from yoke_core.domain.session_message_types import parse_timestamp, timestamp
from yoke_core.domain.session_relay_storage import marker


#: How many times one recipient's wake may be declined by the same running
#: native before the attempts start counting. Comfortably past any transient
#: race with a turn that is genuinely mid-stride, and far short of the
#: unbounded loop that let two sessions sit undeliverable with nothing to
#: show for it. Counting per pid is what keeps a later, unrelated native from
#: inheriting a bound an earlier one used up.
MAX_RESTORED_DEFERRALS = 5


def restore_deferred_wake_budget(
    conn: Any,
    *,
    message_id: str,
    session_id: str,
    now: str,
    running_native_pid: object = None,
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
    # The backoff is owed either way; only the refund is bounded. A recipient
    # this far in is not racing a turn that is about to end.
    declined = _declined_attempts(
        conn,
        message_id=message_id,
        session_id=session_id,
        running_native_pid=running_native_pid,
    )
    # The decline being settled is already stored, so ``declined`` counts it:
    # the bound is reached on the attempt after the last one it refunds.
    # Cadence (the wake_after backoff) does not change; past the bound the
    # receipt escalates so a same-condition loop is visible instead of silent.
    assignments = ["wake_after=" + p]
    values: list[Any] = [backoff]
    if declined <= MAX_RESTORED_DEFERRALS:
        assignments.insert(0, "wake_attempt_count=wake_attempt_count-1")
    else:
        assignments.insert(0, "wake_escalation=" + p)
        values.insert(0, NATIVE_TURN_RUNNING_RESULT)
    conn.execute(
        "UPDATE session_message_recipients SET "
        + ",".join(assignments)
        + " "
        f"WHERE message_id={p} AND session_id={p} AND state='pending' "
        f"AND wake_attempt_count>0 AND wake_after<={p} "
        "AND NOT EXISTS (SELECT 1 FROM session_message_attempts a "
        "WHERE a.message_id=session_message_recipients.message_id "
        "AND a.target_session_id=session_message_recipients.session_id "
        "AND a.attempt_kind IN ('wake_relay','wake_broker') "
        "AND a.completed_at IS NULL)",
        (*values, message_id, session_id, backoff),
    )


def _declined_attempts(
    conn: Any,
    *,
    message_id: str,
    session_id: str,
    running_native_pid: object = None,
) -> int:
    """How many of this recipient's wakes this running native has declined.

    A deferral never delivers, and a recipient that is delivered leaves
    ``pending`` and is never settled here again, so the run for one receipt
    and one pid is also a consecutive run.

    A report that named no pid cannot be attributed, so it falls back to the
    whole receipt rather than restarting the count it could not place.
    """
    p = marker(conn)
    rows = conn.execute(
        "SELECT evidence FROM session_message_attempts "
        f"WHERE message_id={p} AND target_session_id={p} "
        f"AND result_code={p}",
        (message_id, session_id, NATIVE_TURN_RUNNING_RESULT),
    ).fetchall()
    if running_native_pid is None:
        return len(rows)
    return sum(1 for row in rows if _named_pid(row[0]) == running_native_pid)


def _named_pid(evidence: object) -> object:
    """The process a stored decline was made against, if it recorded one."""
    if not isinstance(evidence, str) or not evidence.strip():
        return None
    try:
        document = json.loads(evidence)
    except ValueError:
        return None
    return document.get("running_native_pid") if isinstance(document, dict) else None


__all__ = ["MAX_RESTORED_DEFERRALS", "restore_deferred_wake_budget"]
