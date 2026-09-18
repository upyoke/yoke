"""Which delivery state a live recipient's unread envelope is in.

The classification is the whole finding: the seat owes a move on two of
these states and owes nothing on the rest, so a waiting delivery labelled
as a failure and a failure labelled as waiting are both defects. What
belongs in this view at all -- gone recipients, finished receipts, grouping
-- is covered by ``test_steering_fleet_report_undelivered_scope``.
"""

from __future__ import annotations

import pytest

from runtime.api.steering_fleet_test_helpers import (
    ANSWERER,
    ASKER,
    BEFORE_THAT,
    JUST_NOW,
    LONG_AGO,
    NOW,
    PROJECT_ID,
    seed_delivery_attempt,
    seed_message,
    seed_session,
    seed_tool_call,
)
from yoke_contracts.session_control.wake import EXPLICIT_WAKE_ROUTING_FLAG
from yoke_core.domain.steering_fleet_report_delivery_states import (
    ATTEMPT_FAILED,
    ATTEMPT_IN_FLIGHT,
    AWAITING_ATTEMPT,
    NEVER_ATTEMPTED,
    TURN_IN_FLIGHT,
)
from yoke_core.domain.steering_fleet_report_undelivered import undelivered_messages


#: A turn that ran after :data:`LONG_AGO` and attached nothing, then stopped
#: — hours of silence before :data:`NOW`.
AFTER_THE_SEND = "2026-08-26T09:30:00Z"


@pytest.fixture
def fleet(test_db):
    """Two ordinary workers, quiet since before any message was sent."""
    seed_session(test_db, ASKER, last_tool_call_at=BEFORE_THAT)
    seed_session(test_db, ANSWERER, last_tool_call_at=BEFORE_THAT)
    test_db.commit()
    return test_db


def test_an_envelope_never_injected_to_a_silent_recipient_is_reported(fleet):
    seed_message(fleet, "msg-1", sender=ASKER, to=ANSWERER, at=LONG_AGO)
    fleet.commit()

    rows = undelivered_messages(fleet, project_id=PROJECT_ID, now=NOW)

    assert [entry.session_id for entry in rows] == [ANSWERER]
    assert rows[0].envelope_count == 1
    assert rows[0].delivery_state == NEVER_ATTEMPTED
    assert rows[0].needs_seat_action is True


def test_a_zero_attempt_envelope_is_owed_on_the_recipients_own_silence(fleet):
    """The silence that matters started before the message did.

    A worker quiet for four hours is not going to run the hook that would
    attach an envelope sent two minutes ago, and the plane owes it a wake
    right away. Counting the wait from the send instead bought that envelope
    another grace window of quiet.
    """
    seed_message(fleet, "msg-1", sender=ASKER, to=ANSWERER, at=JUST_NOW)
    fleet.commit()

    rows = undelivered_messages(fleet, project_id=PROJECT_ID, now=NOW)

    assert [entry.session_id for entry in rows] == [ANSWERER]
    assert rows[0].delivery_state == NEVER_ATTEMPTED
    assert rows[0].diagnostic == ""


def test_a_requested_wake_the_plane_never_took_reads_as_queued(fleet):
    """The receipt itself is the obstacle, so the row has to carry it.

    A wake was requested and no attempt was ever made on it. Reported as a
    bare absence of delivery, the seat asks for the wake that this very
    receipt refuses; carried as a queued wake, the row names what to
    release instead.
    """
    seed_message(
        fleet,
        "msg-1",
        sender=ASKER,
        to=ANSWERER,
        at=LONG_AGO,
        routing_snapshot={EXPLICIT_WAKE_ROUTING_FLAG: True},
    )
    fleet.commit()

    rows = undelivered_messages(fleet, project_id=PROJECT_ID, now=NOW)

    assert rows[0].delivery_state == NEVER_ATTEMPTED
    assert rows[0].queued_wake is True


def test_an_ordinary_undelivered_envelope_is_not_a_queued_wake(fleet):
    """No wake was asked for, so there is none to release."""
    seed_message(fleet, "msg-1", sender=ASKER, to=ANSWERER, at=LONG_AGO)
    fleet.commit()

    rows = undelivered_messages(fleet, project_id=PROJECT_ID, now=NOW)

    assert rows[0].delivery_state == NEVER_ATTEMPTED
    assert rows[0].queued_wake is False


def test_a_recipient_that_is_still_running_tool_calls_is_waiting(fleet):
    """Its hooks are running, so the next one attaches this.

    This is the ordinary case, and it must not read as a failure: the seat
    acting on it would chase a delivery that is about to happen anyway. What
    keeps it waiting is the recipient's recent tool call, not the fact that
    one happened after the send — once those stop for a full window the
    plane escalates the same receipt, and this view says so with it.
    """
    seed_message(fleet, "msg-1", sender=ASKER, to=ANSWERER, at=LONG_AGO)
    fleet.execute(
        "UPDATE harness_sessions SET last_tool_call_at = %s WHERE session_id = %s",
        (JUST_NOW, ANSWERER),
    )
    fleet.commit()

    rows = undelivered_messages(fleet, project_id=PROJECT_ID, now=NOW)

    assert [entry.delivery_state for entry in rows] == [AWAITING_ATTEMPT]
    assert rows[0].needs_seat_action is False
    assert rows[0].in_delivery is True


def test_a_recipient_that_ran_a_tool_and_then_stopped_is_owed_an_attempt(fleet):
    """One hook that declined the envelope does not settle its wait.

    The plane escalates this receipt once the recipient's own silence passes
    the window, so a view that read the earlier tool call as an exemption
    would keep calling it waiting while a resume was already in flight.
    """
    seed_message(fleet, "msg-1", sender=ASKER, to=ANSWERER, at=LONG_AGO)
    fleet.execute(
        "UPDATE harness_sessions SET last_tool_call_at = %s WHERE session_id = %s",
        (AFTER_THE_SEND, ANSWERER),
    )
    fleet.commit()

    rows = undelivered_messages(fleet, project_id=PROJECT_ID, now=NOW)

    assert [entry.delivery_state for entry in rows] == [NEVER_ATTEMPTED]
    assert rows[0].needs_seat_action is True


def test_an_envelope_still_inside_the_delivery_sla_reads_as_waiting(fleet):
    """One relay poll to actually make the attempt is not a failure."""
    seed_message(fleet, "msg-1", sender=ASKER, to=ANSWERER, at=NOW)
    fleet.commit()

    rows = undelivered_messages(fleet, project_id=PROJECT_ID, now=NOW)

    assert [entry.delivery_state for entry in rows] == [AWAITING_ATTEMPT]
    assert rows[0].needs_seat_action is False


def test_a_failed_attempt_is_reported_with_its_named_diagnostic(fleet):
    """`failed` alone cannot be acted on; the reason behind it can."""
    seed_message(fleet, "msg-1", sender=ASKER, to=ANSWERER, at=NOW)
    seed_delivery_attempt(
        fleet,
        "attempt-1",
        message_id="msg-1",
        to=ANSWERER,
        result_code="failed",
        evidence={"result_code": "instruction_invalid"},
        started_at=NOW,
    )
    fleet.commit()

    rows = undelivered_messages(fleet, project_id=PROJECT_ID, now=NOW)

    assert [entry.session_id for entry in rows] == [ANSWERER]
    assert rows[0].delivery_state == ATTEMPT_FAILED
    assert rows[0].diagnostic == "instruction_invalid"
    assert rows[0].needs_seat_action is True


def test_a_failed_attempt_with_no_reason_still_says_so(fleet):
    seed_message(fleet, "msg-1", sender=ASKER, to=ANSWERER, at=NOW)
    seed_delivery_attempt(
        fleet, "attempt-1", message_id="msg-1", to=ANSWERER, result_code="failed"
    )
    fleet.commit()

    rows = undelivered_messages(fleet, project_id=PROJECT_ID, now=NOW)

    assert rows[0].diagnostic == "unreported"


def test_an_attempt_still_in_flight_is_waiting_not_failed(fleet):
    """An accepted resume may still deliver, and saying otherwise is the bug.

    Reporting this as a failure sends the seat after a delivery already
    under way; dropping it entirely, as this section once did, left the
    seat unable to tell it from an envelope nothing had ever attempted.
    """
    seed_message(fleet, "msg-1", sender=ASKER, to=ANSWERER, at=LONG_AGO)
    seed_delivery_attempt(
        fleet,
        "attempt-1",
        message_id="msg-1",
        to=ANSWERER,
        result_code="accepted",
        started_at=LONG_AGO,
    )
    fleet.commit()

    rows = undelivered_messages(fleet, project_id=PROJECT_ID, now=NOW)

    assert [entry.delivery_state for entry in rows] == [ATTEMPT_IN_FLIGHT]
    assert rows[0].needs_seat_action is False
    assert rows[0].diagnostic == ""


def test_a_recipient_inside_an_unreturned_call_waits_for_that_calls_hook(fleet):
    """No hook runs until the call returns, so nothing here is stuck."""
    seed_message(fleet, "msg-1", sender=ASKER, to=ANSWERER, at=LONG_AGO)
    seed_tool_call(
        fleet,
        ANSWERER,
        tool_use_id="call-1",
        started_at=LONG_AGO,
        command_summary="yoke watch merge merge-item -- YOK-1 --wait",
    )
    fleet.commit()

    rows = undelivered_messages(fleet, project_id=PROJECT_ID, now=NOW)

    assert [entry.delivery_state for entry in rows] == [TURN_IN_FLIGHT]
    assert rows[0].turn_in_flight_since == LONG_AGO
    assert rows[0].needs_seat_action is False


def test_an_open_call_overtakes_an_earlier_failed_attempt(fleet):
    """The recipient's own turn has moved past that route's refusal."""
    seed_message(fleet, "msg-1", sender=ASKER, to=ANSWERER, at=LONG_AGO)
    seed_delivery_attempt(
        fleet,
        "attempt-1",
        message_id="msg-1",
        to=ANSWERER,
        result_code="failed",
        started_at=LONG_AGO,
    )
    seed_tool_call(
        fleet,
        ANSWERER,
        tool_use_id="call-1",
        started_at=JUST_NOW,
        command_summary="yoke watch pytest --impacted main",
    )
    fleet.commit()

    rows = undelivered_messages(fleet, project_id=PROJECT_ID, now=NOW)

    assert [entry.delivery_state for entry in rows] == [TURN_IN_FLIGHT]


def test_an_open_call_on_a_verified_dead_native_is_not_in_flight(fleet):
    seed_message(fleet, "msg-1", sender=ASKER, to=ANSWERER, at=LONG_AGO)
    seed_tool_call(
        fleet,
        ANSWERER,
        tool_use_id="call-1",
        started_at=LONG_AGO,
        command_summary="yoke watch pytest --impacted main",
    )
    fleet.execute(
        "UPDATE harness_sessions SET last_heartbeat = %s, "
        "native_process_gone_at = %s, native_process_gone_evidence = %s "
        "WHERE session_id = %s",
        (
            BEFORE_THAT,
            JUST_NOW,
            '{"pids":[4002],"process_start_times":{"4002":"t"},"exit_code":143}',
            ANSWERER,
        ),
    )
    fleet.commit()

    rows = undelivered_messages(fleet, project_id=PROJECT_ID, now=NOW)

    assert TURN_IN_FLIGHT not in [entry.delivery_state for entry in rows]


def test_a_desktop_recipient_is_flagged_as_its_operators_to_wake(fleet):
    """The seat cannot revive this one, so the row must say so.

    Everything else about the finding is identical — pending, never
    injected, silent past the window — and the action is completely
    different, because Yoke never resumes an operator-opened chat.
    """
    fleet.execute(
        "UPDATE harness_sessions SET executor_surface = %s WHERE session_id = %s",
        ("claude-desktop", ANSWERER),
    )
    seed_message(fleet, "msg-1", sender=ASKER, to=ANSWERER, at=LONG_AGO)
    seed_message(fleet, "msg-2", sender=ANSWERER, to=ASKER, at=LONG_AGO)
    fleet.commit()

    operator_wake = {
        entry.session_id: entry.operator_wake
        for entry in undelivered_messages(fleet, project_id=PROJECT_ID, now=NOW)
    }

    assert operator_wake == {ANSWERER: True, ASKER: False}

