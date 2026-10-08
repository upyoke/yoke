"""Disappearance explanations share report cooldown, framing and read budget."""

import io
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from yoke_core.domain.fleet_delta_reports import ReportState, append_steering_reports
from yoke_core.domain.fleet_delta_snapshot import STEERING_REPORT_FUNCTION
from yoke_core.domain.steering_fleet_report_render import REPORT_BEGIN, REPORT_END

NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)
REF = "held-candidate"


def test_disappearance_is_inside_the_next_report_once_without_extra_reads():
    state = ReportState()
    output = io.StringIO()
    reports = [
        {
            "fingerprint": "before",
            "digest": f"{REPORT_BEGIN}\nlanding row\n{REPORT_END}",
            "scopes": [
                {
                    "descriptor": "project",
                    "idle_after_seconds": 1200,
                    "holders": [{"public_ref": REF, "idle_seconds": 1800}],
                    "landings": [{"public_ref": REF, "pr_number": "17"}],
                }
            ],
        },
        {
            "fingerprint": "after",
            "digest": f"{REPORT_BEGIN}\nquiet\n{REPORT_END}",
            "scopes": [
                {
                    "descriptor": "project",
                    "idle_after_seconds": 1200,
                    "holders": [{"public_ref": REF, "idle_seconds": 0}],
                    "landings": [],
                }
            ],
        },
    ]
    calls = []

    def call(function, payload):
        calls.append(function)
        result = (
            reports.pop(0)
            if function == STEERING_REPORT_FUNCTION
            else {"settings_json": "{}"}
        )
        return SimpleNamespace(success=True, result=result)

    for minutes in (0, 1, 2):
        append_steering_reports(
            ["project"],
            observed_at=NOW + timedelta(minutes=minutes),
            stream=output,
            call=call,
            state=state,
        )
    assert calls.count(STEERING_REPORT_FUNCTION) == 2
    text = output.getvalue()
    assert text.count("no longer listed — worker active again") == 1
    assert text.rindex("no longer listed") < text.rindex(REPORT_END)
    assert state.rows == {}
    # An unchanged follow-up does not wake or repeat the removal.
    append_steering_reports(
        ["project"],
        observed_at=NOW + timedelta(minutes=4),
        stream=output,
        call=lambda *_: SimpleNamespace(success=True, result={"settings_json": "{}"}),
        state=state,
        report={
            "fingerprint": "after",
            "digest": f"{REPORT_BEGIN}\nquiet\n{REPORT_END}",
            "scopes": [],
        },
    )
    assert output.getvalue() == text


def test_unreadable_report_preserves_previously_displayed_rows():
    state = ReportState()
    output = io.StringIO()

    def policy(*_):
        return SimpleNamespace(success=True, result={"settings_json": "{}"})

    before = {
        "fingerprint": "same",
        "body": "report",
        "scopes": [
            {"descriptor": "project", "deployment_runs": [{"run_id": "run-one"}]}
        ],
    }
    append_steering_reports(
        ["project"],
        observed_at=NOW,
        stream=output,
        call=policy,
        state=state,
        report=before,
    )
    old_rows = dict(state.rows)
    append_steering_reports(
        ["project"],
        observed_at=NOW + timedelta(minutes=2),
        stream=output,
        call=policy,
        state=state,
        report={"fingerprint": "bad"},
    )
    assert state.rows == old_rows
    after = {
        "fingerprint": "same",
        "body": "report",
        "scopes": [{"descriptor": "project", "deployment_runs": []}],
    }
    append_steering_reports(
        ["project"],
        observed_at=NOW + timedelta(minutes=3),
        stream=output,
        call=policy,
        state=state,
        report=after,
    )
    assert output.getvalue().count("no longer listed — run finished") == 1
    assert state.rows == {}


def test_a_report_the_session_already_received_is_not_printed_again():
    """The shared record says the hook delivered it; only departures print."""
    state = ReportState()
    output = io.StringIO()
    scope = {
        "descriptor": "project",
        "idle_after_seconds": 1200,
        "holders": [{"public_ref": REF, "idle_seconds": 0}],
        "landings": [{"public_ref": REF, "pr_number": "17"}],
    }
    reports = [
        {"fingerprint": "a", "digest": "first", "delivered": True, "scopes": [scope]},
        {"fingerprint": "a", "digest": "first", "delivered": False, "scopes": [scope]},
        {
            "fingerprint": "b",
            "digest": "second",
            "delivered": False,
            "scopes": [{**scope, "landings": []}],
        },
    ]

    def call(function, payload):
        result = (
            reports.pop(0)
            if function == STEERING_REPORT_FUNCTION
            else {"settings_json": "{}"}
        )
        return SimpleNamespace(success=True, result=result)

    for minutes in (0, 5, 10):
        append_steering_reports(
            ["project"],
            observed_at=NOW + timedelta(minutes=minutes),
            stream=output,
            call=call,
            state=state,
        )
    text = output.getvalue()
    assert text.count("first") == 1
    assert "second" not in text
    assert text.count("no longer listed:") == 1
