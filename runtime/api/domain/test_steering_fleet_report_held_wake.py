"""The undelivered state for a wake the machine is holding back.

``native_turn_running`` is deliberately not a failure -- the relay made the
right call -- so it classified as an attempt in flight, whose line promises a
delivery moments away. Every observed run of it repeats for hours. Its
sibling ``test_steering_fleet_report_undelivered`` holds the other seven
states; this holds the eighth and the silence measurement that tells a turn
which is thinking from one that has stopped.
"""

from __future__ import annotations

import pytest

from runtime.api.steering_fleet_test_helpers import (
    ANSWERER,
    ASKER,
    BEFORE_THAT,
    LONG_AGO,
    NOW,
    PROJECT_ID,
    seed_delivery_attempt,
    seed_message,
    seed_session,
)
from yoke_core.domain.steering_fleet_report_delivery_states import (
    WAKE_HELD_FOR_NATIVE_TURN,
)
from yoke_core.domain.steering_fleet_report_undelivered import undelivered_messages


@pytest.fixture
def fleet(test_db):
    """Two ordinary workers, quiet since before any message was sent."""
    seed_session(test_db, ASKER, last_tool_call_at=BEFORE_THAT)
    seed_session(test_db, ANSWERER, last_tool_call_at=BEFORE_THAT)
    test_db.commit()
    return test_db


def _held(fleet, *, evidence=None):
    seed_message(fleet, "msg-1", sender=ASKER, to=ANSWERER, at=LONG_AGO)
    seed_delivery_attempt(
        fleet,
        "attempt-1",
        message_id="msg-1",
        to=ANSWERER,
        result_code="native_turn_running",
        evidence=evidence,
        started_at=LONG_AGO,
    )
    fleet.commit()
    return undelivered_messages(fleet, project_id=PROJECT_ID, now=NOW)


def test_a_wake_the_machine_held_back_is_neither_failed_nor_in_flight(fleet):
    """The machine refused to start a second turn, and nothing is moving.

    ``native_turn_running`` is deliberately not a failure -- the relay made
    the right call -- so it classified as an attempt in flight, and a seat
    reading the row was told a delivery was moments away every time the
    same refusal repeated. Every observed run of it repeats for hours, so
    the state it needed was one of its own.
    """
    rows = _held(fleet)

    assert [entry.delivery_state for entry in rows] == [WAKE_HELD_FOR_NATIVE_TURN]


def test_the_held_row_carries_the_silence_the_machine_measured(fleet):
    """The measurement has to survive evidence redaction to be worth making.

    Attempt evidence passes a bounded allowlist that drops every field it
    does not know, so a fact the relay reports is not automatically a fact a
    seat can read.
    """
    rows = _held(fleet, evidence={"running_native_silent_for_seconds": 1800})

    assert rows[0].delivery_state == WAKE_HELD_FOR_NATIVE_TURN
    assert rows[0].held_native_silent_for_seconds == 1800


def test_an_unmeasured_silence_leaves_the_row_saying_nothing(fleet):
    """A held row that claimed zero would read as a turn that just spoke."""
    rows = _held(fleet)

    assert rows[0].held_native_silent_for_seconds is None
