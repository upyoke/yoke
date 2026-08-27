"""A wake is settled by the envelope arriving, never by the resume starting."""

from __future__ import annotations

import json

import pytest

from runtime.api.domain.test_session_wake_reconciliation import _add_events_table
from runtime.api.domain.test_session_relay import (
    RELAY_ID,
    _add_wake_recipient,
    _clock,
    _connection,
    _heartbeat,
)
from yoke_contracts.session_control.wake_delivery import (
    NATIVE_RESUME_ACCEPTED_RESULT,
    TURN_WITHOUT_INJECTION_RECOVERY,
    TURN_WITHOUT_INJECTION_RESULT,
    WAKE_DELIVERED_RESULT,
    WAKE_REPORT_CODES,
)
from yoke_contracts.session_control.wake_instruction import (
    WAKE_DELIVERY_COMMAND,
    native_wake_instruction,
)
from yoke_core.domain.session_broker_wake import DIRECT_FALLBACK_RESULTS
from yoke_core.domain.session_message_wake import wake_eligible_recipients
from yoke_core.domain.session_message_types import parse_timestamp
from yoke_core.domain.session_relay import claim_relay_job, report_relay_job
from yoke_core.domain.session_wake_reconciliation import (
    EVENT_SESSION_WAKE_OUTCOME_RECORDED,
    reconcile_spawned_wake_attempts,
)


STARTED_AT = "2026-08-22T12:00:00Z"
#: ``fleet.wake_ack_grace_seconds`` is 300, so this is one second past it.
PAST_GRACE = "2026-08-22T12:05:01Z"
INSIDE_GRACE = "2026-08-22T12:04:00Z"


def _accepted_wake(conn) -> str:
    """Claim one wake and report exactly what a fire-and-forget native says."""
    claimed = claim_relay_job(
        conn, _heartbeat(), wait_seconds=0, now_provider=_clock(STARTED_AT)
    )
    job = claimed.jobs[0]
    report_relay_job(
        conn,
        actor_id=1,
        relay_id=RELAY_ID,
        job_kind="wake",
        job_id=job.job_id,
        lease_id=job.lease_id,
        result_code=NATIVE_RESUME_ACCEPTED_RESULT,
        adapter_revision="cursor-native-v2",
        evidence={},
        now="2026-08-22T12:00:01Z",
    )
    return job.job_id


def _attempt(conn, attempt_id: str):
    return conn.execute(
        "SELECT completed_at,result_code,evidence FROM session_message_attempts "
        "WHERE attempt_id=?",
        (attempt_id,),
    ).fetchone()


def _inject(conn, at: str = "2026-08-22T12:00:30Z") -> None:
    conn.execute(
        "UPDATE session_message_recipients SET state='injected',"
        "injection_count=1,last_injected_at=? WHERE message_id='message-1'",
        (at,),
    )
    conn.commit()


def test_the_wake_instruction_names_the_tool_call_that_delivers() -> None:
    """The turn is told to run a command, not merely told a message exists."""
    instruction = native_wake_instruction("message-1")

    assert WAKE_DELIVERY_COMMAND in instruction
    assert "first action" in instruction
    # The one case where acknowledging would report a delivery that never
    # happened stays named.
    assert "do not acknowledge" in instruction


def test_an_accepted_resume_is_not_yet_an_outcome() -> None:
    conn = _connection()
    _add_wake_recipient(conn)

    attempt_id = _accepted_wake(conn)

    row = _attempt(conn, attempt_id)
    assert row[0] is None
    assert row[1] == NATIVE_RESUME_ACCEPTED_RESULT


def test_an_injected_envelope_settles_the_wake_delivered() -> None:
    conn = _connection()
    _add_wake_recipient(conn)
    attempt_id = _accepted_wake(conn)
    _inject(conn)

    assert reconcile_spawned_wake_attempts(conn, now=INSIDE_GRACE) == 1

    row = _attempt(conn, attempt_id)
    assert tuple(row[:2]) == (INSIDE_GRACE, WAKE_DELIVERED_RESULT)
    evidence = json.loads(row[2])
    assert evidence["injection_count"] == 1
    assert evidence["transport_result"] == NATIVE_RESUME_ACCEPTED_RESULT


def test_an_acknowledged_envelope_settles_the_wake_delivered() -> None:
    """A hook that injects and acknowledges in one turn may report only the ack."""
    conn = _connection()
    _add_wake_recipient(conn)
    attempt_id = _accepted_wake(conn)
    conn.execute(
        "UPDATE session_message_recipients SET state='acknowledged',"
        "acknowledged_at=? WHERE message_id='message-1'",
        ("2026-08-22T12:00:30Z",),
    )
    conn.commit()

    assert reconcile_spawned_wake_attempts(conn, now=INSIDE_GRACE) == 1
    assert _attempt(conn, attempt_id)[1] == WAKE_DELIVERED_RESULT


def test_a_resume_that_delivered_nothing_is_a_named_failure() -> None:
    conn = _connection()
    _add_wake_recipient(conn)
    attempt_id = _accepted_wake(conn)

    assert reconcile_spawned_wake_attempts(conn, now=PAST_GRACE) == 1

    row = _attempt(conn, attempt_id)
    assert tuple(row[:2]) == (PAST_GRACE, TURN_WITHOUT_INJECTION_RESULT)
    evidence = json.loads(row[2])
    assert evidence["injection_count"] == 0
    assert evidence["receipt_state"] == "pending"


def test_an_undelivered_verdict_teaches_its_recovery() -> None:
    """The event is the only record of a wake that reported nothing wrong."""
    conn = _connection()
    _add_events_table(conn)
    _add_wake_recipient(conn)
    _accepted_wake(conn)

    reconcile_spawned_wake_attempts(conn, now=PAST_GRACE)

    envelope = conn.execute(
        "SELECT envelope FROM events WHERE event_name=?",
        (EVENT_SESSION_WAKE_OUTCOME_RECORDED,),
    ).fetchone()[0]
    context = json.loads(envelope)["context"]
    assert context["result_code"] == TURN_WITHOUT_INJECTION_RESULT
    assert context["recovery"] == TURN_WITHOUT_INJECTION_RECOVERY


def test_a_turn_still_inside_its_delivery_window_stays_open() -> None:
    conn = _connection()
    _add_wake_recipient(conn)
    attempt_id = _accepted_wake(conn)

    assert reconcile_spawned_wake_attempts(conn, now=INSIDE_GRACE) == 0
    assert _attempt(conn, attempt_id)[0] is None


def test_an_undelivered_wake_frees_the_receipt_for_the_next_attempt() -> None:
    """The ladder keeps escalating; it does not stop on a reported success."""
    conn = _connection()
    _add_wake_recipient(conn)
    _accepted_wake(conn)

    assert wake_eligible_recipients(conn, now=parse_timestamp(PAST_GRACE)) == []
    reconcile_spawned_wake_attempts(conn, now=PAST_GRACE)
    conn.commit()

    eligible = wake_eligible_recipients(conn, now=parse_timestamp(PAST_GRACE))
    assert [row["message_id"] for row in eligible] == ["message-1"]


def test_an_undelivered_direct_wake_hands_the_next_one_to_the_broker() -> None:
    assert TURN_WITHOUT_INJECTION_RESULT in DIRECT_FALLBACK_RESULTS


@pytest.mark.parametrize(
    "verdict", (WAKE_DELIVERED_RESULT, TURN_WITHOUT_INJECTION_RESULT)
)
def test_no_relay_may_report_a_delivery_verdict(verdict: str) -> None:
    """Delivery is the control plane's to observe, never the relay's to claim."""
    assert verdict not in WAKE_REPORT_CODES
