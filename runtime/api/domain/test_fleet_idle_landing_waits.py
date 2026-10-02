"""The fleet alarm reads the same landing facts as the held-scope report."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from yoke_core.domain.fleet_delta_alarms import DeltaState, idle_holder_alarms
from yoke_core.domain.fleet_delta_probe import _ReportState, _append_steering_reports
from yoke_core.domain.fleet_delta_snapshot import (
    ENVELOPES_FUNCTION,
    FRONTIER_FUNCTION,
    SESSIONS_FUNCTION,
    STEERING_REPORT_FUNCTION,
    FleetReadError,
    read_snapshot,
)

NOW = datetime(2026, 8, 28, 17, 0, tzinfo=timezone.utc)
HELD_REF = "held-candidate"
HEALTHY = {
    "public_ref": HELD_REF,
    "in_flight": True,
    "merged": False,
    "closed": False,
    "failed_checks": [],
    "wake_delivered": False,
}


def _snapshot(readbacks, *, report_ok=True, held=HELD_REF):
    calls = []
    report = {
        "scopes": [{"landings": readbacks}],
        "fingerprint": "same",
        "body": "report",
    }

    def call(function, payload):
        calls.append(function)
        results = {
            SESSIONS_FUNCTION: {
                "rows": [
                    {
                        "session_id": "holder",
                        "mode": "dash",
                        "activity_at": (NOW - timedelta(hours=1)).isoformat(),
                        "claims": [{"target_kind": "item", "target": held}],
                    }
                ]
            },
            FRONTIER_FUNCTION: {},
            ENVELOPES_FUNCTION: {},
            STEERING_REPORT_FUNCTION: report,
        }
        if function == STEERING_REPORT_FUNCTION and not report_ok:
            return SimpleNamespace(
                success=False,
                error=SimpleNamespace(code="unreadable", message="retry report"),
            )
        return SimpleNamespace(success=True, result=results[function])

    snapshot = read_snapshot(["project"], call=call, now=NOW, self_session_id="seat")
    return snapshot, calls


def test_healthy_landing_excludes_idle_alarm_and_due_report_reuses_its_read():
    import io

    snapshot, calls = _snapshot([HEALTHY])
    assert idle_holder_alarms(snapshot, DeltaState()) == []
    assert calls.count(STEERING_REPORT_FUNCTION) == 1

    def policy_only(function, payload):
        assert function != STEERING_REPORT_FUNCTION
        return SimpleNamespace(success=True, result={"settings_json": "{}"})

    output = io.StringIO()
    _append_steering_reports(
        ["project"],
        observed_at=NOW,
        stream=output,
        call=policy_only,
        state=_ReportState(),
        report=snapshot.landing_report,
    )
    assert output.getvalue() == "report\n"


@pytest.mark.parametrize(
    "overrides",
    [
        {"in_flight": False},
        {"closed": True},
        {"in_flight": None},
        {"failed_checks": [{"name": "tests", "conclusion": "FAILURE"}]},
        {"wake_delivered": True},
    ],
)
def test_dead_failed_unreadable_and_delivered_landings_alarm(overrides):
    snapshot, _ = _snapshot([{**HEALTHY, **overrides}])
    assert "ALARM idle-holder" in idle_holder_alarms(snapshot, DeltaState())[0]


def test_a_landing_belonging_to_another_holder_does_not_hide_the_alarm():
    snapshot, _ = _snapshot([{**HEALTHY, "public_ref": "other-candidate"}])
    assert "ALARM idle-holder" in idle_holder_alarms(snapshot, DeltaState())[0]


def test_merged_landing_alarms_only_after_the_completion_wake_is_delivered():
    merged = {**HEALTHY, "in_flight": False, "closed": True, "merged": True}
    before, _ = _snapshot([merged])
    after, _ = _snapshot([{**merged, "wake_delivered": True}])
    assert idle_holder_alarms(before, DeltaState()) == []
    assert "ALARM idle-holder" in idle_holder_alarms(after, DeltaState())[0]


def test_an_unreadable_report_refuses_the_pass_instead_of_guessing_a_wait():
    with pytest.raises(FleetReadError, match="steering.report.get: unreadable"):
        _snapshot([], report_ok=False)


def test_a_serving_build_without_landing_fields_keeps_the_prior_alarm():
    snapshot, _ = _snapshot([{"public_ref": HELD_REF}])
    assert "ALARM idle-holder" in idle_holder_alarms(snapshot, DeltaState())[0]
