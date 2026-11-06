"""Only current running sessions can excuse an unfinished call row."""

from datetime import timedelta

import pytest

from yoke_core.domain.session_state import session_in_flight
from yoke_core.domain.steering_fleet_report_delivery_states import (
    delivery_state,
    TURN_IN_FLIGHT,
    NEVER_ATTEMPTED,
)
from yoke_core.domain.steering_fleet_report_detectors import parse_stamp

START = "2026-08-26T11:40:00Z"
NOW = "2026-08-26T12:00:00Z"


def running():
    return {
        "turn_posture": "running",
        "last_tool_call_at": START,
        "open_tool_call_since": START,
    }


@pytest.mark.parametrize(
    "extra",
    [
        {"turn_posture": "unknown"},
        {"turn_posture": "waiting"},
        {"ended_at": NOW},
        {"terminated_at": NOW},
        {
            "native_process_gone_at": NOW,
            "native_process_gone_evidence": '{"exit_code":0}',
        },
        {"last_tool_call_at": NOW},
    ],
)
def test_dead_stopped_or_superseded_call_never_hides_queued_messages(extra):
    record = {**running(), **extra}
    assert not session_in_flight({**record, "open_tool_call_at": START}, now=parse_stamp(NOW))
    assert (
        delivery_state(
            record,
            result_code="",
            sent_at=START,
            grace=timedelta(seconds=30),
            sla=timedelta(seconds=30),
            current=parse_stamp(NOW),
        )
        != TURN_IN_FLIGHT
    )


def test_live_call_still_waits_for_its_hook():
    assert session_in_flight({**running(), "open_tool_call_at": START}, now=parse_stamp(NOW))
    assert (
        delivery_state(
            running(),
            result_code="",
            sent_at=START,
            grace=timedelta(seconds=30),
            sla=timedelta(seconds=30),
            current=parse_stamp(NOW),
        )
        == TURN_IN_FLIGHT
    )


def test_stopped_turn_raises_the_normal_owed_delivery_alarm():
    record = {**running(), "turn_posture": "waiting"}
    assert (
        delivery_state(
            record,
            result_code="",
            sent_at=START,
            grace=timedelta(seconds=30),
            sla=timedelta(seconds=30),
            current=parse_stamp(NOW),
        )
        == NEVER_ATTEMPTED
    )
