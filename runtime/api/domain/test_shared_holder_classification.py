"""Report and fleet agree on the shared state, including project idle settings."""

from datetime import datetime, timedelta, timezone

import pytest

from yoke_core.domain.fleet_delta_alarms import DeltaState, idle_holder_alarms
from yoke_core.domain.fleet_delta_snapshot import FleetSnapshot, session_rows
from yoke_core.domain.session_state import session_needs_idle_alarm
from yoke_core.domain.steering_fleet_report_holders import (
    ClaimHolder,
    with_session_state,
)

NOW = datetime(2026, 11, 6, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "mode,wait,minutes,expected",
    [
        ("dash", {}, 10, True),
        ("dash", {}, 30, False),
        ("parked", {}, 10, False),
        (
            "dash",
            {"pending_decision": {"actor": "operator", "reason": "choose"}},
            10,
            False,
        ),
        (
            "dash",
            {"dependency_wait": {"actor": "another_item", "reason": "blocked"}},
            10,
            False,
        ),
        ("dash", {"ci_wait": {"actor": "ci_or_deploy", "reason": "checks"}}, 10, False),
    ],
)
def test_report_and_alarm_share_intent_actor_and_idle_setting(
    mode, wait, minutes, expected
):
    stamp = NOW - timedelta(minutes=21)
    holder = ClaimHolder(
        "worker",
        1,
        "work",
        mode,
        mode == "parked",
        stamp,
        1260,
        quiet_reason="waiting for direction",
        state_facts=wait,
    )
    [holder] = with_session_state((holder,), now=NOW, idle_after_seconds=60 * minutes)
    model = holder.session_state
    rows = session_rows(
        {
            "rows": [
                {
                    "session_id": "worker",
                    "session_state": model,
                    "mode": mode,
                    "last_tool_call_at": stamp,
                    "claims": [{"target_kind": "item", "target": "work"}],
                }
            ]
        }
    )
    lines = idle_holder_alarms(FleetSnapshot(NOW, "seat", sessions=rows), DeltaState())
    assert session_needs_idle_alarm(model) is expected
    assert bool(lines) is expected
    if wait:
        assert model["intent"]["state"] == "awaiting"
        assert model["intent"]["reason"] == next(iter(wait.values()))["reason"]
