"""Start-gap reports refuse incomplete evidence instead of inventing gains."""

import json
import pytest
from yoke_core.domain.deployment_start_timing import PREFIX
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
    return "\n".join(
        PREFIX
        + json.dumps(
            {
                "run_id": "run-report",
                "source_sha": "a" * 40,
                "member_count": 4,
                "transport": "local-postgres",
                **record,
            }
        )
        for record in records
    )


def test_report_compares_start_gap_with_supplied_baseline():
    report = start_report(_capture(), run_id="run-report", baseline_seconds=300)
    assert report["start_gap_seconds"] == 120
    assert report["reduction_seconds"] == 180
    assert report["context_builds"] == 1
    assert report["step_elapsed_ms"]["composition_freeze"] == 100


@pytest.mark.parametrize(
    "capture,reason",
    [
        ("", "start_timing_incomplete"),
        (_capture(extra_context=True), "start_context_count"),
        (_capture(missing="pin_read"), "start_steps_missing"),
    ],
)
def test_incomplete_or_duplicate_capture_is_refused(capture, reason):
    with pytest.raises(StartEvidenceError, match=reason):
        start_report(capture, run_id="run-report", baseline_seconds=300)


def test_report_finds_numeric_project_capture_from_slug(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from yoke_core.tools import deployment_start_report as report

    raw = (
        tmp_path
        / "1/sessions/session/runs/pid-1/watcher-captures/yoke-deploy.raw.test.log"
    )
    raw.parent.mkdir(parents=True)
    raw.write_text(_capture())
    monkeypatch.setattr(report, "global_scratch_root", lambda: tmp_path)
    monkeypatch.setattr(report, "resolve_active_project", lambda _project: "project")

    def dispatch(**kwargs):
        value = 1 if kwargs["payload"]["field"] == "id" else "project"
        return SimpleNamespace(success=True, result={"value": value})

    monkeypatch.setattr(
        "yoke_core.api.service_client_structured_api_adapter.call_dispatcher", dispatch
    )
    assert report.find_capture("run-report") == raw
