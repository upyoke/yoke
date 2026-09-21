"""The refund a declining native gives back stops, so the loop cannot hide.

Its sibling ``test_session_wake_deferral`` holds what one refund does and how
two reports of it race. This holds the bound: how many declines one holding
process may refund before the attempts start counting, and that a different
process starts its own run.
"""

from __future__ import annotations

from yoke_contracts.session_control.wake_delivery import NATIVE_TURN_RUNNING_RESULT
from yoke_core.domain.session_relay import report_relay_job
from yoke_core.domain.session_wake_deferral import MAX_RESTORED_DEFERRALS
from runtime.api.domain.test_session_relay import (
    RELAY_ID,
    _add_wake_recipient,
    _connection,
)
from runtime.api.domain.test_session_wake_deferral import (
    RUNNING_NATIVE,
    _claim_wake,
    _recipient,
)

def _defer_once(conn, *, round_index: int, pid: int = RUNNING_NATIVE.pid) -> None:
    """Claim and decline one wake, far enough on to clear the backoff.

    The rounds stay inside the fixture relay's connected window; drifting
    past it makes the recipient unclaimable for an unrelated reason.
    """
    minute = 30 + round_index * 2
    job = _claim_wake(conn, now=f"2026-08-22T11:{minute:02d}:00Z")
    report_relay_job(
        conn,
        actor_id=1,
        relay_id=RELAY_ID,
        job_kind="wake",
        job_id=job.job_id,
        lease_id=job.lease_id,
        result_code=NATIVE_TURN_RUNNING_RESULT,
        adapter_revision="relay-custody-v1",
        evidence={**RUNNING_NATIVE.evidence, "running_native_pid": pid},
        now=f"2026-08-22T11:{minute:02d}:02Z",
    )


def test_the_refund_stops_so_a_declined_recipient_stops_churning() -> None:
    """An unbounded refund is how a blocked recipient stayed invisible.

    Every decline gave the attempt straight back, so the count never moved
    off zero and the recipient re-qualified on the next poll forever -- one
    session was declined fourteen times in seventeen minutes with nothing
    to show for it. Past the bound the attempts count, the recipient reaches
    its wake limit, and it stops taking a wake slot every poll.
    """
    conn = _connection()
    _add_wake_recipient(conn)

    for index in range(MAX_RESTORED_DEFERRALS):
        _defer_once(conn, round_index=index)
        assert _recipient(conn)[0] == 0, "a refund is owed inside the bound"

    _defer_once(conn, round_index=MAX_RESTORED_DEFERRALS)

    count, _wake_after, state = _recipient(conn)
    assert count == 1
    # Nothing is killed and nothing is lost: the envelope stays pending, so
    # a turn that really is running still delivers it on its next hook.
    assert state == "pending"


def test_the_same_non_transient_decline_escalates_past_the_bound() -> None:
    """Six identical running-turn declines with an empty escalation is silence.

    The bound already stops the refund. Escalation names the condition the
    wake could not reach so the seat can act instead of watching retries.
    """
    conn = _connection()
    _add_wake_recipient(conn)

    for index in range(MAX_RESTORED_DEFERRALS):
        _defer_once(conn, round_index=index)
        escalation = conn.execute(
            "SELECT wake_escalation FROM session_message_recipients "
            "WHERE message_id='message-1'"
        ).fetchone()[0]
        assert not escalation

    _defer_once(conn, round_index=MAX_RESTORED_DEFERRALS)
    escalation = conn.execute(
        "SELECT wake_escalation FROM session_message_recipients "
        "WHERE message_id='message-1'"
    ).fetchone()[0]
    assert escalation == NATIVE_TURN_RUNNING_RESULT


def test_a_different_native_does_not_inherit_the_spent_bound() -> None:
    """The bound is per holding process, so a new one starts its own.

    A later native declining this recipient is a new situation: the run that
    exhausted the bound belonged to a process that is gone.
    """
    conn = _connection()
    _add_wake_recipient(conn)
    for index in range(MAX_RESTORED_DEFERRALS):
        _defer_once(conn, round_index=index)

    _defer_once(conn, round_index=MAX_RESTORED_DEFERRALS, pid=RUNNING_NATIVE.pid + 1)

    assert _recipient(conn)[0] == 0
