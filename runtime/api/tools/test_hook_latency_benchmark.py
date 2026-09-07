from __future__ import annotations

import json
import subprocess

import pytest

from yoke_cli.hook_latency_benchmark import (
    BenchmarkRefusal,
    attach_durable_phases,
    compare_reports,
    parse_provenance,
    run_benchmark,
)


def _dispatch_row(row_id: int, event: str, evaluator_ms, client_wall_ms):
    context = {
        "evaluator": "resident",
        "resident_warm_duration_ms": 100,
    }
    if client_wall_ms is not None:
        context["client_wall_ms"] = client_wall_ms
    return {
        "id": str(row_id),
        "duration_ms": "" if evaluator_ms is None else str(evaluator_ms),
        "envelope": json.dumps({"hook_event_name": event, "context": context}),
    }


def test_durable_phase_attachment_keeps_missing_distinct_from_zero() -> None:
    samples = [{"ordinal": 1, "pre_phase": None, "post_phase": None}]

    attach_durable_phases(
        samples,
        [
            _dispatch_row(2, "PostToolUse", None, 12),
            _dispatch_row(1, "PreToolUse", 0, 0),
        ],
    )

    assert samples[0]["pre_phase"]["evaluator_ms"] == 0
    assert samples[0]["pre_phase"]["client_wall_ms"] == 0
    assert samples[0]["post_phase"]["evaluator_ms"] is None
    assert samples[0]["post_phase"]["client_wall_ms"] == 12


def test_provenance_parser_reads_available_revisions() -> None:
    assert parse_provenance(
        "yoke-provenance client sha=abc kind=wheel path=/client "
        "server sha=def kind=checkout path=/server\n"
    ) == {"client_revision": "abc", "server_revision": "def"}


def test_small_benchmark_runs_normal_pre_and_post_hooks() -> None:
    calls: list[tuple[str, ...]] = []

    def fake_run(argv, **kwargs):
        tokens = tuple(str(value) for value in argv)
        calls.append(tokens)
        if "identity" in tokens:
            stdout = json.dumps(
                {
                    "result": {
                        "session_id": "session-1",
                        "executor": "codex",
                        "executor_surface": "codex-cli",
                    }
                }
            )
            return subprocess.CompletedProcess(argv, 0, stdout, "")
        if "list" in tokens:
            stdout = json.dumps(
                {
                    "result": {
                        "rows": [
                            {"turn_posture": "running"},
                            {"turn_posture": "waiting"},
                        ]
                    }
                }
            )
            return subprocess.CompletedProcess(argv, 0, stdout, "")
        if "events" in tokens:
            rows = [
                _dispatch_row(4, "PostToolUse", 4, 6),
                _dispatch_row(3, "PreToolUse", 3, 5),
                _dispatch_row(2, "PostToolUse", 4, 6),
                _dispatch_row(1, "PreToolUse", 3, 5),
            ]
            return subprocess.CompletedProcess(
                argv, 0, json.dumps({"result": {"rows": rows}}), ""
            )
        if "evaluate" in tokens:
            stderr = (
                "yoke-provenance client sha=abc kind=wheel path=/client "
                "server sha=def kind=checkout path=/server\n"
            )
            return subprocess.CompletedProcess(argv, 0, "", stderr)
        return subprocess.CompletedProcess(argv, 0, "", "")

    report = run_benchmark(2, run=fake_run)

    assert report["status"] == "complete"
    assert report["run_count"] == 2
    assert report["harness"] == "codex"
    assert report["surface"] == "codex-cli"
    assert report["client_revision"] == "abc"
    assert report["server_revision"] == "def"
    assert report["summary"]["phase_record_count"] == 4
    assert report["summary"]["evaluator_timing_coverage_pct"] == 100.0
    assert report["summary"]["client_wall_timing_coverage_pct"] == 100.0
    assert report["samples"][0]["pre_phase"]["evaluator_ms"] == 3
    assert report["samples"][0]["pre_phase"]["client_unattributed_ms"] == 2
    assert {sample["status"] for sample in report["samples"]} == {"complete"}
    evidence = report["concurrency_evidence"]
    assert evidence["start"] == {
        "live_roster_count": 2,
        "tool_active_bucket_proxy_count": 1,
    }
    assert evidence["end"] == evidence["start"]
    assert sum("PreToolUse" in call for call in calls) == 2
    assert sum("PostToolUse" in call for call in calls) == 2


def test_comparison_rejects_different_harness_and_incomplete_coverage() -> None:
    current = {
        "harness": "codex",
        "surface": "codex-cli",
        "client_revision": "a",
        "server_revision": "b",
        "command": "/usr/bin/true",
        "run_count": 5,
        "summary": {
            "evaluator_timing_coverage_pct": 100.0,
            "client_wall_timing_coverage_pct": 100.0,
            "envelope_ms_mean": 20,
        },
    }
    baseline = {
        "harness": "cursor",
        "surface": "cursor-cli",
        "client_revision": "a",
        "server_revision": "b",
        "command": "/usr/bin/true",
        "run_count": 5,
        "summary": {
            "evaluator_timing_coverage_pct": 100.0,
            "client_wall_timing_coverage_pct": 50.0,
            "envelope_ms_mean": 10,
        },
    }

    comparison = compare_reports(current, baseline)

    assert comparison["status"] == "incomparable"
    assert "harness differs" in comparison["reasons"]
    assert "baseline client-wall timing coverage is 50.0%" in comparison["reasons"]
    assert comparison["mean_delta_ms"]["envelope_ms_mean"] == 10


def test_benchmark_rejects_unbounded_sample_count() -> None:
    with pytest.raises(BenchmarkRefusal, match="sample count must be between"):
        run_benchmark(21)
