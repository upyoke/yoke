from __future__ import annotations

import json
import subprocess

import pytest

from yoke_cli.hook_latency_benchmark import (
    BenchmarkRefusal,
    attach_durable_phases,
    compare_reports,
    parse_provenance,
    phase_coverage,
    run_benchmark,
)


def _dispatch_row(
    row_id: int, event: str, evaluator_ms, client_wall_ms, tool_use_id="call-1"
):
    context = {
        "evaluator": "resident",
        "resident_warm_duration_ms": 100,
    }
    if client_wall_ms is not None:
        context["client_wall_ms"] = client_wall_ms
    if tool_use_id is not None:
        context["tool_use_id"] = tool_use_id
    return {
        "id": str(row_id),
        "duration_ms": "" if evaluator_ms is None else str(evaluator_ms),
        "envelope": json.dumps({"hook_event_name": event, "context": context}),
    }


def _sample(ordinal: int, tool_use_id: str) -> dict:
    return {
        "ordinal": ordinal,
        "tool_use_id": tool_use_id,
        "pre_phase": None,
        "post_phase": None,
    }


def test_durable_phase_attachment_keeps_missing_distinct_from_zero() -> None:
    samples = [_sample(1, "call-1")]

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


def test_attachment_ignores_unrelated_hooks_from_the_same_session() -> None:
    """A neighbouring tool call's rows never become this sample's timings."""
    samples = [_sample(1, "call-1")]

    attach_durable_phases(
        samples,
        [
            _dispatch_row(1, "PreToolUse", 90, 91, tool_use_id="unrelated"),
            _dispatch_row(2, "PreToolUse", 3, 5),
            _dispatch_row(3, "PostToolUse", 60, 61, tool_use_id="unrelated"),
            _dispatch_row(4, "PostToolUse", 4, 6),
            _dispatch_row(5, "PreToolUse", 70, 71, tool_use_id=None),
        ],
    )

    assert samples[0]["pre_phase"]["evaluator_ms"] == 3
    assert samples[0]["post_phase"]["evaluator_ms"] == 4


def test_attachment_survives_reordered_pre_and_post_insertion() -> None:
    """Post landing before Pre is an insertion order, not a phase swap."""
    samples = [_sample(1, "call-1"), _sample(2, "call-2")]

    attach_durable_phases(
        samples,
        [
            _dispatch_row(1, "PostToolUse", 40, 41, tool_use_id="call-2"),
            _dispatch_row(2, "PostToolUse", 20, 21, tool_use_id="call-1"),
            _dispatch_row(3, "PreToolUse", 30, 31, tool_use_id="call-2"),
            _dispatch_row(4, "PreToolUse", 10, 11, tool_use_id="call-1"),
        ],
    )

    assert samples[0]["pre_phase"]["evaluator_ms"] == 10
    assert samples[0]["post_phase"]["evaluator_ms"] == 20
    assert samples[1]["pre_phase"]["evaluator_ms"] == 30
    assert samples[1]["post_phase"]["evaluator_ms"] == 40


def test_partial_delivery_attaches_what_landed_and_names_what_did_not() -> None:
    """A phase still in the resident's queue is reported, never guessed."""
    samples = [_sample(1, "call-1"), _sample(2, "call-2")]

    attach_durable_phases(
        samples,
        [
            _dispatch_row(1, "PreToolUse", 10, 11, tool_use_id="call-1"),
            _dispatch_row(2, "PostToolUse", 20, 21, tool_use_id="call-1"),
            _dispatch_row(3, "PreToolUse", 30, 31, tool_use_id="call-2"),
        ],
    )
    coverage = phase_coverage(samples, dispatch_row_count=3, dispatch_row_limit=54)

    assert samples[1]["pre_phase"]["evaluator_ms"] == 30
    assert samples[1]["post_phase"] is None
    assert coverage["dispatch_row_limit_reached"] is False
    assert coverage["missing_phases"] == [
        {
            "ordinal": 2,
            "phase": "post_phase",
            "hook_event": "PostToolUse",
            "reason": "no HookDispatchTelemetry row names this call identity",
        }
    ]


def test_coverage_names_the_row_limit_when_the_query_filled_it() -> None:
    samples = [_sample(1, "call-1")]

    coverage = phase_coverage(samples, dispatch_row_count=52, dispatch_row_limit=52)

    assert coverage["dispatch_row_limit_reached"] is True
    assert len(coverage["missing_phases"]) == 2
    assert "full row limit" in coverage["missing_phases"][0]["reason"]


def test_provenance_parser_reads_available_revisions() -> None:
    assert parse_provenance(
        "yoke-provenance client sha=abc kind=wheel path=/client "
        "server sha=def kind=checkout path=/server\n"
    ) == {"client_revision": "abc", "server_revision": "def"}


def test_small_benchmark_runs_normal_pre_and_post_hooks() -> None:
    calls: list[tuple[str, ...]] = []
    hook_identities: list[str] = []

    def fake_run(argv, **kwargs):
        tokens = tuple(str(value) for value in argv)
        calls.append(tokens)
        if "evaluate" in tokens:
            hook_identities.append(json.loads(kwargs["input"])["tool_use_id"])
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
            first, second = hook_identities[0], hook_identities[2]
            rows = [
                # A prior run's row and an unrelated same-session hook the
                # bounded window still caught: both stay unattached.
                _dispatch_row(6, "PreToolUse", 99, 99, tool_use_id="earlier-run"),
                _dispatch_row(5, "PostToolUse", 98, 98, tool_use_id="unrelated"),
                _dispatch_row(4, "PostToolUse", 4, 6, tool_use_id=second),
                _dispatch_row(3, "PreToolUse", 3, 5, tool_use_id=second),
                _dispatch_row(2, "PostToolUse", 4, 6, tool_use_id=first),
                _dispatch_row(1, "PreToolUse", 3, 5, tool_use_id=first),
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
    assert report["phase_coverage"]["missing_phases"] == []
    assert len(set(hook_identities)) == 2, "each sample owns one call identity"
    query = next(call for call in calls if "events" in call)
    assert "--since" in query, "the dispatch query is bounded to this run"
    assert query[query.index("--limit") + 1] == "54"


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
