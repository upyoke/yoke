"""When a held-wake row offers to terminate the native holding it.

A turn still inside the widest watcher budget may only be waiting on a slow
call -- a model-provider stall read as "kill it" once -- so the row names the
terminate lever only once the measured silence reaches
``IN_FLIGHT_CEILING_SECONDS``. Every other word of the row stays as it was,
and nothing on it claims why the turn is quiet.
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
from yoke_contracts.session_control.liveness import IN_FLIGHT_CEILING_SECONDS
from yoke_core.domain.steering_fleet_report_delivery_states import (
    WAKE_HELD_FOR_NATIVE_TURN,
)
from yoke_core.domain.steering_fleet_report_render_undelivered import (
    undelivered_line,
)
from yoke_core.domain.steering_fleet_report_undelivered import (
    UndeliveredMessages,
    undelivered_messages,
)

SESSION = "held-session"


def _line(silent: int | None) -> str:
    return undelivered_line(
        UndeliveredMessages(
            session_id=SESSION,
            delivery_state=WAKE_HELD_FOR_NATIVE_TURN,
            envelope_count=1,
            oldest_seconds=600,
            held_native_silent_for_seconds=silent,
        )
    )


@pytest.mark.parametrize("silent", [0, 600, IN_FLIGHT_CEILING_SECONDS - 1])
def test_a_held_row_under_the_ceiling_offers_no_terminate(silent):
    line = _line(silent)
    assert "native turn running" in line
    assert "it delivers at that session's next tool call or when its turn ends" in line
    assert "terminate" not in line


@pytest.mark.parametrize(
    "silent", [IN_FLIGHT_CEILING_SECONDS, IN_FLIGHT_CEILING_SECONDS + 3600]
)
def test_a_held_row_at_or_over_the_ceiling_offers_terminate(silent):
    line = _line(silent)
    assert "native turn running" in line
    assert f"; to end it: `yoke sessions terminate {SESSION} --reason ...`" in line


_CHILD = {
    "running_native_pid": 4001,
    "running_native_background_pid": 4120,
    "running_native_background_command": "npm run build",
    "running_native_background_count": 1,
    "running_native_silent_for_seconds": 600,
}


@pytest.fixture
def fleet(test_db):
    seed_session(test_db, ASKER, last_tool_call_at=BEFORE_THAT)
    seed_session(test_db, ANSWERER, last_tool_call_at=BEFORE_THAT)
    seed_message(test_db, "msg-1", sender=ASKER, to=ANSWERER, at=LONG_AGO)
    seed_delivery_attempt(
        test_db,
        "attempt-1",
        message_id="msg-1",
        to=ANSWERER,
        result_code="native_turn_running",
        evidence=_CHILD,
        started_at=LONG_AGO,
    )
    test_db.commit()
    return test_db


def _held_line(fleet, posture: str, at: str) -> str:
    fleet.execute(
        "UPDATE harness_sessions SET turn_posture=%s, turn_posture_at=%s "
        "WHERE session_id=%s",
        (posture, at, ANSWERER),
    )
    fleet.commit()
    rows = undelivered_messages(fleet, project_id=PROJECT_ID, now=NOW)
    assert rows[0].delivery_state == WAKE_HELD_FOR_NATIVE_TURN
    return undelivered_line(rows[0])


def test_a_running_turn_with_a_background_child_claims_no_cause(fleet):
    line = _held_line(fleet, "running", "2026-08-26T08:01:00Z")
    assert "wake held — native turn running" in line
    assert "model" not in line
    assert "background" not in line
    assert "terminate" not in line


def test_the_background_task_line_still_shows_when_the_turn_ended(fleet):
    line = _held_line(fleet, "waiting", "2026-08-26T08:01:00Z")
    assert "held by background child 4120 `npm run build`" in line
    assert "delivers when it returns; ending it delivers now" in line
    assert "model" not in line
    assert "terminate" not in line
