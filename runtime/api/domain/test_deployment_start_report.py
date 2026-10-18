"""Start-gap reports refuse incomplete evidence instead of inventing gains."""

from types import SimpleNamespace

import pytest
from yoke_core.tools.deployment_start_report import start_report, StartEvidenceError


def _capture(*, extra_context=False, missing=None):
    steps = [
        "pin_read",
        "worktree_retirement",
        "worktree_ensure",
        "child_start",
        "execution_context",
        "branch_verification",
        "qa_seed",
        "containment_attestation",
        "composition_freeze",
        "executing_stamp",
    ]
    records = [
        {
            "step": "driver_preflight",
            "phase": "start",
            "timestamp": "2026-10-03T00:00:00+00:00",
        }
    ]
    records += [
        {"step": s, "phase": "end", "elapsed_ms": 100, "outcome": "ok"}
        for s in steps
        if s != missing
    ]
    records += [
        {
            "step": "executing_transition",
            "phase": "end",
            "outcome": "ok",
            "elapsed_ms": 200,
            "timestamp": "2026-10-03T00:02:00+00:00",
        }
    ]
    if extra_context:
        records.append({"step": "execution_context", "phase": "end", "elapsed_ms": 100})
    return [
        {
            "run_id": "run-report",
            "source_sha": "a" * 40,
            "member_count": 4,
            "transport": "local-postgres",
            **record,
        }
        for record in records
    ]


def test_report_compares_start_gap_with_supplied_baseline():
    report = start_report(_capture(), run_id="run-report", baseline_seconds=300)
    assert report["start_gap_seconds"] == 120
    assert report["reduction_seconds"] == 180
    assert report["context_builds"] == 1
    assert report["step_elapsed_ms"]["composition_freeze"] == 100


@pytest.mark.parametrize(
    "capture,reason",
    [
        ([], "start_timing_incomplete"),
        (_capture(extra_context=True), "start_context_count"),
        (_capture(missing="pin_read"), "start_steps_missing"),
    ],
)
def test_incomplete_or_duplicate_capture_is_refused(capture, reason):
    with pytest.raises(StartEvidenceError, match=reason):
        start_report(capture, run_id="run-report", baseline_seconds=300)


def test_report_reads_the_registered_timings(monkeypatch, capsys):
    from yoke_core.tools import deployment_start_report as report

    calls = []

    def dispatch(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(success=True, result={"records": _capture()})

    monkeypatch.setattr(
        "yoke_core.api.service_client_structured_api_adapter.call_dispatcher", dispatch
    )
    assert report.main(["--run-id", "run-report", "--baseline-seconds", "300"]) == 0
    assert calls[0]["function_id"] == "deployment_runs.timings"
    assert calls[0]["target"].workflow_run_id == "run-report"
    assert '"start_gap_seconds": 120.0' in capsys.readouterr().out


def test_report_names_an_unserved_timings_read(monkeypatch, capsys):
    from yoke_core.tools import deployment_start_report as report

    error = SimpleNamespace(code="function_not_served", message="below floor")
    monkeypatch.setattr(
        "yoke_core.api.service_client_structured_api_adapter.call_dispatcher",
        lambda **_: SimpleNamespace(success=False, error=error, result=None),
    )
    assert report.main(["--run-id", "run-report", "--baseline-seconds", "3"]) == 1
    out = capsys.readouterr().out
    assert "start_timings_unavailable: function_not_served: below floor" in out
