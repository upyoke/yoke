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
    seed_tool_call,
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
    from yoke_core.domain.steering_fleet_report_render_undelivered import (
        undelivered_line,
    )

    observed = rows[0].held_native_observed_at
    assert observed is not None
    assert f"silent for 30m as of {observed:%H:%MZ}" in undelivered_line(rows[0])


def test_an_unmeasured_silence_leaves_the_row_saying_nothing(fleet):
    """A held row that claimed zero would read as a turn that just spoke."""
    rows = _held(fleet)

    assert rows[0].held_native_silent_for_seconds is None


@pytest.mark.parametrize(
    ("tool_at", "silent", "expected"),
    [
        ("2026-08-26T11:55:00Z", 5400, 300),
        ("2026-08-26T10:00:00Z", 1800, 1800),
        ("2026-08-26T12:01:00Z", 5400, 0),
        ("2026-08-26T11:55:00Z", None, None),
    ],
)
def test_held_silence_uses_recent_tool_activity(fleet, tool_at, silent, expected):
    """Completed calls count even when the session activity cache is stale."""
    seed_tool_call(
        fleet,
        ANSWERER,
        tool_use_id="latest-call",
        started_at=tool_at,
        completed_at=tool_at,
        command_summary="Read item status",
    )
    # Insert older history last so the query must select the latest start.
    seed_tool_call(
        fleet,
        ANSWERER,
        tool_use_id="older-call",
        started_at=BEFORE_THAT,
        completed_at=BEFORE_THAT,
        command_summary="Read earlier status",
    )
    evidence = {} if silent is None else {"running_native_silent_for_seconds": silent}
    rows = _held(fleet, evidence=evidence)

    assert rows[0].delivery_state == WAKE_HELD_FOR_NATIVE_TURN
    assert rows[0].held_native_silent_for_seconds == expected
    from yoke_core.domain.steering_fleet_report_render_undelivered import (
        undelivered_line,
    )

    line = undelivered_line(rows[0])
    assert "it delivers at that session's next tool call or when its turn ends" in line
    if expected == 300:
        assert "silent for 5m as of 12:00Z" in line
    if expected is None:
        assert "silent for" not in line


_CHILD = {
    "running_native_pid": 4001,
    "running_native_background_pid": 4120,
    "running_native_background_command": "gh run watch 9876",
    "running_native_background_count": 1,
}


def _posture(fleet, posture: str, at: str) -> None:
    fleet.execute(
        "UPDATE harness_sessions SET turn_posture=%s, turn_posture_at=%s "
        "WHERE session_id=%s",
        (posture, at, ANSWERER),
    )


def test_an_ended_turn_names_the_background_child_holding_it(fleet):
    """A Stop newer than the last tool call: the hold is the child, not a turn."""
    _posture(fleet, "waiting", "2026-08-26T08:01:00Z")
    rows = _held(fleet, evidence={**_CHILD, "running_native_silent_for_seconds": 600})
    from yoke_core.domain.steering_fleet_report_render_undelivered import (
        undelivered_line,
    )

    assert rows[0].delivery_state == WAKE_HELD_FOR_NATIVE_TURN
    line = undelivered_line(rows[0])
    assert "turn ended at 2026-08-26T08:01:00.000000Z" in line
    assert "held by background child 4120 `gh run watch 9876`" in line
    assert "delivers when it returns" in line
    assert "native turn running" not in line
    # Silence is still measured as before, from capture output and tool calls.
    assert "silent for 10m" in line


def test_an_ended_turn_without_named_children_still_says_so(fleet):
    """A relay that predates the child fields names none, and says that."""
    _posture(fleet, "waiting", "2026-08-26T08:01:00Z")
    from yoke_core.domain.steering_fleet_report_render_undelivered import (
        undelivered_line,
    )

    line = undelivered_line(_held(fleet, evidence={"running_native_pid": 4001})[0])
    assert "turn ended at 2026-08-26T08:01:00.000000Z; process held by background task(s)" in line


@pytest.mark.parametrize(
    ("posture", "posture_at", "call_at"),
    [
        # No Stop since the last tool call: the turn is still running.
        ("waiting", "2026-08-26T07:59:00Z", None),
        ("running", "2026-08-26T08:01:00Z", None),
        # A completed call after the Stop opened another turn.
        ("waiting", "2026-08-26T08:01:00Z", "2026-08-26T08:02:00Z"),
    ],
)
def test_a_running_turn_still_reads_native_turn_running(
    fleet, posture, posture_at, call_at
):
    _posture(fleet, posture, posture_at)
    if call_at:
        seed_tool_call(
            fleet, ANSWERER, tool_use_id="after-stop", started_at=call_at,
            completed_at=call_at, command_summary="Run tests",
        )
    from yoke_core.domain.steering_fleet_report_render_undelivered import (
        undelivered_line,
    )

    rows = _held(fleet, evidence=_CHILD)
    assert rows[0].delivery_state == WAKE_HELD_FOR_NATIVE_TURN
    assert rows[0].held_turn_ended_at is None
    line = undelivered_line(rows[0])
    assert "wake held — native turn running" in line
    assert "turn ended" not in line
