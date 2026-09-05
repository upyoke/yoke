"""What one undelivered-messages row tells the seat to do about it.

Seven shapes reach this section and they divide three ways: two the seat
owes a move, three still on their way, and two beyond anyone's reach. The
line has to separate them, because before it did a seat watching a machine
where every wake refused saw only a worker that had gone quiet.
"""

from __future__ import annotations

from dataclasses import replace

from runtime.api.domain.test_steering_fleet_report_populated_body import (
    _populated_report,
    report_body,
)
from yoke_core.domain.steering_fleet_report_delivery_states import (
    ATTEMPT_FAILED,
    ATTEMPT_IN_FLIGHT,
    AWAITING_ATTEMPT,
    NEVER_ATTEMPTED,
    RECIPIENT_ENDED,
    RECIPIENT_TERMINATED,
    TURN_IN_FLIGHT,
)
from yoke_core.domain.steering_fleet_report_undelivered import UndeliveredMessages

SESSION = "undelivered-session"


def _row(**overrides) -> str:
    entry = UndeliveredMessages(
        session_id=SESSION,
        delivery_state=overrides.pop("delivery_state", NEVER_ATTEMPTED),
        envelope_count=overrides.pop("envelope_count", 1),
        oldest_seconds=overrides.pop("oldest_seconds", 600),
        **overrides,
    )
    body = report_body(replace(_populated_report(), undelivered=(entry,)))
    return next(line for line in body.splitlines() if SESSION in line)


def test_a_row_says_who_owes_the_next_move():
    """A CLI row names its escalation; a desktop row names its operator.

    They are different asks: one is a resume already in flight, the other
    a chat only the person reading it can open.
    """
    escalated = _row(wake_escalation="starved_hook_route")
    operator = _row(wake_escalation="starved_hook_route", operator_wake=True)

    assert "wake escalated (starved_hook_route)" in escalated
    assert "waiting for the operator to wake it" in operator
    assert "wake escalated" not in operator


def test_a_row_says_what_was_tried_and_how_it_ended():
    """`never injected` alone cannot separate no attempt from a failed one.

    Those need opposite moves — one says the plane skipped the receipt, the
    other names a refusal to go fix — and for two hours a seat watching a
    machine where every wake refused for one nameable reason saw neither.
    """
    assert "no delivery attempted" in _row(delivery_state=NEVER_ATTEMPTED)
    assert "last attempt failed (instruction_invalid)" in _row(
        delivery_state=ATTEMPT_FAILED, diagnostic="instruction_invalid"
    )


def test_a_delivery_still_under_way_reads_as_waiting_not_as_a_failure():
    """The whole point of naming the state: waiting must not read as failed."""
    in_flight = _row(delivery_state=ATTEMPT_IN_FLIGHT)
    queued = _row(delivery_state=AWAITING_ATTEMPT)

    assert "delivery attempt in flight — waiting" in in_flight
    assert "queued for the recipient's next hook — waiting" in queued
    for line in (in_flight, queued):
        assert "failed" not in line
        assert "no delivery attempted" not in line


def test_a_recipient_mid_call_is_left_alone():
    """Nothing is owed, nothing failed, and the seat should not resume it."""
    line = _row(
        delivery_state=TURN_IN_FLIGHT, turn_in_flight_since="2026-08-26T11:39:00Z"
    )

    assert "recipient turn in flight since 2026-08-26T11:39:00Z" in line
    assert "no resume" in line


def test_a_gone_recipient_names_the_loss_and_proposes_no_revival():
    """Two absences, told apart, with no recipe either can be fixed by.

    The envelope stays addressed to the session it was sent to, so a row
    that suggested waking a terminated session would be proposing something
    that cannot happen.
    """
    ended = _row(
        delivery_state=RECIPIENT_ENDED, recipient_gone_at="2026-08-26T11:58:00Z"
    )
    terminated = _row(
        delivery_state=RECIPIENT_TERMINATED,
        recipient_gone_at="2026-08-26T11:58:00Z",
        wake_escalation="starved_hook_route",
        operator_wake=True,
    )

    assert "recipient session ended 2026-08-26T11:58:00Z" in ended
    assert "no delivery route remains" in ended
    assert "recipient session terminated 2026-08-26T11:58:00Z" in terminated
    for line in (ended, terminated):
        assert "wake" not in line
        assert "resume" not in line


def test_a_row_names_the_envelopes_it_counts():
    """A seat that cannot look the message up cannot assess it."""
    line = _row(envelope_count=5, message_ids=("msg-1", "msg-2", "msg-3"))

    assert "5 message(s) [msg-1 msg-2 msg-3 +2]" in line
