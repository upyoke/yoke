"""Diagnostic clocks remain exact and cannot manufacture verification evidence."""

from datetime import datetime
import json
from pathlib import Path

import pytest

from yoke_contracts import timestamps
from yoke_contracts.timestamps import InvalidInstant, parse_instant
from yoke_core.domain import deployment_start_timing as timing
from yoke_core.tools import atlas_integrity_audit as atlas
from yoke_core.tools import yoke_ci_tree_reuse as reuse
from yoke_core.tools.deployment_start_report import StartEvidenceError, start_report


QUALIFIED = "1970-01-01T05:44:59.123456+05:45"
CANONICAL = "1969-12-31T23:59:59.123456Z"
INSTANT = parse_instant(QUALIFIED)


@pytest.mark.parametrize(
    "invalid", ["", "1970-01-01", "1970-01-01T00:00:00", 0, False, datetime(1970, 1, 1)]
)
def test_owned_report_clock_refuses_before_collection(invalid, monkeypatch) -> None:
    monkeypatch.setattr(
        atlas,
        "collect_function_registry",
        lambda: pytest.fail("collector ran before clock validation"),
    )
    with pytest.raises(InvalidInstant):
        atlas.build_report(Path("/tmp"), generated_at=invalid)


@pytest.mark.parametrize(
    "invalid", ["", "1970-01-01", "1970-01-01T00:00:00", 0, False, datetime(1970, 1, 1)]
)
def test_reuse_clock_refuses_before_git_or_api(invalid, monkeypatch) -> None:
    monkeypatch.setattr(
        reuse,
        "tree_object_id",
        lambda *_: pytest.fail("git ran before clock validation"),
    )
    with pytest.raises(InvalidInstant):
        reuse.decide_reuse(
            worktree="/tmp",
            api_url="https://example.test",
            repository="example/project",
            token="test",
            current_run_id=1,
            now=invalid,
        )
    assert reuse._parse_github_time(invalid) is None


def test_external_reuse_clock_retains_microseconds_and_explicit_offset() -> None:
    assert reuse._parse_github_time(QUALIFIED) == INSTANT
    assert reuse._parse_github_time(None) is None


def test_future_reuse_evidence_cannot_skip_suite(monkeypatch) -> None:
    monkeypatch.setattr(reuse, "tree_object_id", lambda *_: "tree")
    monkeypatch.setattr(
        reuse,
        "list_successful_workflow_runs",
        lambda **_: [
            {"id": 2, "created_at": "1969-12-31T23:59:59.123457Z", "head_sha": "head"}
        ],
    )
    result = reuse.decide_reuse(
        worktree="/tmp",
        api_url="https://example.test",
        repository="example/project",
        token="test",
        current_run_id=1,
        now=INSTANT,
    )
    assert not result.skip_suite


def test_start_markers_format_wall_clock_without_changing_elapsed_clock(
    monkeypatch, capsys
) -> None:
    monkeypatch.setattr(timestamps, "utc_now", lambda: INSTANT)
    monkeypatch.setattr(timing, "_transport", lambda: "https")
    clock = iter([4.0, 4.125])
    monkeypatch.setattr(timing, "monotonic", lambda: next(clock))
    with timing.timing_scope("run-clock"):
        with timing.start_step("qa_seed"):
            pass
    records = [
        json.loads(line.removeprefix(timing.PREFIX))
        for line in capsys.readouterr().out.splitlines()
    ]
    assert [r["timestamp"] for r in records] == [CANONICAL, CANONICAL]
    assert records[1]["elapsed_ms"] == 125


def _replace_capture_clocks(first, last) -> str:
    from runtime.api.domain.test_deployment_start_report import _capture

    lines = []
    for line in _capture().splitlines():
        record = json.loads(line.removeprefix(timing.PREFIX))
        if record["step"] == "driver_preflight":
            record["timestamp"] = first
        if record["step"] == "executing_transition":
            record["timestamp"] = last
        lines.append(timing.PREFIX + json.dumps(record))
    return "\n".join(lines)


def test_start_report_measures_offset_and_microseconds() -> None:
    text = _replace_capture_clocks(QUALIFIED, "1970-01-01T00:00:00.124057Z")
    report = start_report(text, run_id="run-report", baseline_seconds=3)
    assert report["start_gap_seconds"] == 1.001


@pytest.mark.parametrize(
    "invalid", [None, "", "1970-01-01", 0, False, "1970-01-01T00:00:00"]
)
def test_start_report_refuses_unqualified_supplied_clock(invalid) -> None:
    text = _replace_capture_clocks(invalid, CANONICAL)
    with pytest.raises(StartEvidenceError, match="start_clock_invalid"):
        start_report(text, run_id="run-report", baseline_seconds=3)
