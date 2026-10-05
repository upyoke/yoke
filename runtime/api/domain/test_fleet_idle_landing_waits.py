"""Light probe landing facts and due-only full report composition."""

from datetime import datetime, timedelta, timezone
import io
from types import SimpleNamespace

import pytest

from yoke_core.domain.fleet_delta_alarms import DeltaState, idle_holder_alarms
from yoke_core.domain.fleet_delta_reports import ReportState, append_steering_reports
from yoke_core.domain.fleet_delta_snapshot import (
    ENVELOPES_FUNCTION,
    FRONTIER_FUNCTION,
    SESSIONS_FUNCTION,
    STEERING_REPORT_FUNCTION,
    read_snapshot,
)
from yoke_core.domain.steering_fleet_report_landings import landing_wait_pending

NOW = datetime(2026, 8, 28, 17, 0, tzinfo=timezone.utc)
HELD_REF = "held-candidate"
HEALTHY = dict(
    in_flight=True, merged=False, closed=False, failed_checks=[], wake_delivered=False
)


def _snapshot(*, awaiting_landing=False):
    calls = []

    def call(function, payload):
        calls.append(function)
        results = {
            SESSIONS_FUNCTION: {
                "rows": [
                    {
                        "session_id": "holder",
                        "mode": "dash",
                        "activity_at": (NOW - timedelta(hours=1)).isoformat(),
                        "claims": [
                            {
                                "target_kind": "item",
                                "target": HELD_REF,
                                "item_awaiting_landing": awaiting_landing,
                            }
                        ],
                    }
                ]
            },
            FRONTIER_FUNCTION: {},
            ENVELOPES_FUNCTION: {},
        }
        assert function != STEERING_REPORT_FUNCTION
        return SimpleNamespace(success=True, result=results[function])

    return read_snapshot(["project"], call=call, now=NOW, self_session_id="seat"), calls


def test_probe_uses_roster_landing_wait_without_reading_full_report():
    snapshot, calls = _snapshot(awaiting_landing=True)
    assert idle_holder_alarms(snapshot, DeltaState()) == []
    assert STEERING_REPORT_FUNCTION not in calls
    assert snapshot.landing_waits == frozenset({HELD_REF})


@pytest.mark.parametrize("awaiting_landing", [False, None])
def test_merged_or_missing_landing_fact_retains_normal_idle_alarm(awaiting_landing):
    snapshot, calls = _snapshot(awaiting_landing=awaiting_landing)
    assert "ALARM idle-holder" in idle_holder_alarms(snapshot, DeltaState())[0]
    assert STEERING_REPORT_FUNCTION not in calls


def test_full_report_is_read_only_when_due_even_with_idle_holder():
    snapshot, _ = _snapshot()
    calls = []

    def call(function, payload):
        calls.append(function)
        result = (
            {"fingerprint": "same", "body": "report"}
            if function == STEERING_REPORT_FUNCTION
            else {"settings_json": "{}"}
        )
        return SimpleNamespace(success=True, result=result)

    state = ReportState()
    stream = io.StringIO()
    for minute in (0, 1, 2):
        append_steering_reports(
            ["project"],
            observed_at=NOW + timedelta(minutes=minute),
            stream=stream,
            call=call,
            state=state,
            snapshot=snapshot,
        )
        assert calls.count(STEERING_REPORT_FUNCTION) == (1 if minute < 2 else 2)
    assert stream.getvalue() == "report\n"


@pytest.mark.parametrize(
    "overrides",
    [
        {"in_flight": False},
        {"closed": True},
        {"in_flight": None},
        {"failed_checks": [{"name": "tests", "conclusion": "FAILURE"}]},
        {"merged": True},
        {"wake_delivered": True},
    ],
)
def test_only_healthy_open_or_queued_landing_excuses_silence(overrides):
    assert landing_wait_pending(HEALTHY)
    assert not landing_wait_pending({**HEALTHY, **overrides})
