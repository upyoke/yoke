"""The benchmark's live roster reads in bounded pages and keeps refusals."""

from __future__ import annotations

import json
import subprocess

import pytest

from yoke_cli.hook_latency_benchmark import (
    ROSTER_PAGE_SIZE,
    BenchmarkRefusal,
    _roster_evidence,
    run_benchmark,
)


def _roster_run(rosters: dict[str, list[dict]], calls: list[tuple[str, ...]]):
    """Serve one status-filtered page per call, as the bounded list does."""

    def fake_run(argv, **_kwargs):
        tokens = tuple(str(value) for value in argv)
        calls.append(tokens)
        assert "--full" in tokens
        status = tokens[tokens.index("--status") + 1]
        limit = int(tokens[tokens.index("--limit") + 1])
        offset = int(tokens[tokens.index("--offset") + 1])
        assert limit == ROSTER_PAGE_SIZE == 25
        rows = rosters[status][offset : offset + limit]
        stdout = json.dumps({"success": True, "result": {"rows": rows}})
        return subprocess.CompletedProcess(argv, 0, stdout, "")

    return fake_run


def _rows(count: int, running: int) -> list[dict]:
    return [
        {"turn_posture": "running" if index < running else "waiting"}
        for index in range(count)
    ]


def _pages(calls, status):
    return [
        int(call[call.index("--offset") + 1])
        for call in calls
        if call[call.index("--status") + 1] == status
    ]


def test_roster_pages_working_and_idle_with_explicit_offsets() -> None:
    calls: list[tuple[str, ...]] = []
    rosters = {"working": _rows(60, 40), "idle": _rows(7, 2)}

    evidence = _roster_evidence(_roster_run(rosters, calls), {})

    assert evidence == {
        "live_roster_count": 67,
        "tool_active_bucket_proxy_count": 42,
    }
    assert _pages(calls, "working") == [0, 25, 50]
    assert _pages(calls, "idle") == [0]
    assert not any("ended" in call for call in calls), "history is never scanned"


def test_exact_page_size_boundary_stops_on_the_empty_page() -> None:
    calls: list[tuple[str, ...]] = []
    rosters = {"working": _rows(50, 50), "idle": []}

    evidence = _roster_evidence(_roster_run(rosters, calls), {})

    assert evidence == {
        "live_roster_count": 50,
        "tool_active_bucket_proxy_count": 50,
    }
    assert _pages(calls, "working") == [0, 25, 50]
    assert _pages(calls, "idle") == [0]


def _refusing_run(stdout: str, stderr: str = ""):
    def fake_run(argv, **_kwargs):
        tokens = tuple(str(value) for value in argv)
        if "identity" in tokens:
            identity = {"result": {"session_id": "s-1", "executor": "codex"}}
            return subprocess.CompletedProcess(argv, 0, json.dumps(identity), "")
        if "list" in tokens and "25" in tokens[tokens.index("--offset") :]:
            return subprocess.CompletedProcess(argv, 1, stdout, stderr)
        rows = {"rows": _rows(25, 0)}
        return subprocess.CompletedProcess(argv, 0, json.dumps({"result": rows}), "")

    return fake_run


def test_structured_refusal_keeps_its_code_message_and_recovery() -> None:
    envelope = {
        "success": False,
        "result": {},
        "error": {
            "code": "https_transport_failed",
            "message": "HTTPS response exceeded the reply size limit",
            "recovery_hint": "narrow the read and retry",
        },
    }

    with pytest.raises(BenchmarkRefusal) as caught:
        run_benchmark(1, run=_refusing_run(json.dumps(envelope), "noise"))

    refusal = caught.value
    assert refusal.code == "https_transport_failed"
    assert "HTTPS response exceeded the reply size limit" in refusal.detail
    assert "sessions list --full --status working" in refusal.detail
    assert refusal.recovery == "narrow the read and retry"


def test_structured_refusal_without_hint_names_a_recovery_step() -> None:
    envelope = {"success": False, "error": {"code": "denied", "message": "no"}}

    with pytest.raises(BenchmarkRefusal) as caught:
        run_benchmark(1, run=_refusing_run(json.dumps(envelope)))

    assert caught.value.code == "denied"
    assert "denied refusal" in caught.value.recovery
    assert "rerun the benchmark" in caught.value.recovery


def test_unstructured_failure_still_reports_stderr() -> None:
    with pytest.raises(BenchmarkRefusal) as caught:
        run_benchmark(1, run=_refusing_run("", "connection refused"))

    assert caught.value.code == "HOOK_BENCHMARK_CONTEXT_UNAVAILABLE"
    assert "connection refused" in caught.value.detail
