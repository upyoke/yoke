"""On-demand, policy-preserving benchmark for one harmless tool command."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Sequence

from yoke_cli.hook_latency_benchmark_report import (
    BenchmarkRefusal,
    attach_durable_phases,
    compare_reports,
    load_report,
    parse_provenance,
    summarize_samples,
)


SAMPLE_COMMAND = (shutil.which("true") or "/usr/bin/true",)
_CLI_CODE = (
    "import sys; from yoke_cli.main import main; raise SystemExit(main(sys.argv[1:]))"
)
Run = Callable[..., subprocess.CompletedProcess[str]]


def _cli_argv(*args: str) -> list[str]:
    return [sys.executable, "-c", _CLI_CODE, *args]


def _run_json(run: Run, args: Sequence[str], env: Mapping[str, str]) -> dict[str, Any]:
    completed = run(
        _cli_argv(*args, "--json"),
        capture_output=True,
        text=True,
        env=dict(env),
        check=False,
    )
    if completed.returncode != 0:
        raise BenchmarkRefusal(
            "HOOK_BENCHMARK_CONTEXT_UNAVAILABLE",
            completed.stderr.strip() or "diagnostic read failed",
            "restore the active Yoke connection and registered session, then rerun",
        )
    try:
        response = json.loads(completed.stdout)
        result = response["result"]
    except (KeyError, TypeError, ValueError) as exc:
        raise BenchmarkRefusal(
            "HOOK_BENCHMARK_CONTEXT_INVALID",
            f"diagnostic read returned no result ({type(exc).__name__})",
            "run `yoke sessions identity --json` and repair the reported context",
        ) from None
    return result


def _run_hook(
    run: Run,
    event_name: str,
    payload: Mapping[str, Any],
    env: Mapping[str, str],
) -> tuple[int, subprocess.CompletedProcess[str]]:
    started = time.perf_counter_ns()
    completed = run(
        _cli_argv("hook", "evaluate", event_name),
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=dict(env),
        check=False,
    )
    elapsed_ms = max(0, int((time.perf_counter_ns() - started) / 1_000_000))
    if completed.returncode != 0:
        detail = (completed.stdout + completed.stderr).strip()
        raise BenchmarkRefusal(
            f"HOOK_BENCHMARK_{event_name.upper()}_REFUSED",
            detail or f"{event_name} exited {completed.returncode}",
            "resolve the named hook policy refusal and rerun the benchmark",
        )
    return elapsed_ms, completed


def _roster_evidence(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    return {
        "live_roster_count": len(rows),
        "tool_active_bucket_proxy_count": sum(
            1 for row in rows if row.get("turn_posture") == "running"
        ),
    }


def run_benchmark(sample_count: int, *, run: Run = subprocess.run) -> dict[str, Any]:
    if isinstance(sample_count, bool) or not 1 <= sample_count <= 20:
        raise BenchmarkRefusal(
            "HOOK_BENCHMARK_SAMPLE_COUNT_INVALID",
            "sample count must be between 1 and 20",
            "choose a small fixed count such as 5",
        )
    env = dict(os.environ)
    identity = _run_json(run, ("sessions", "identity"), env)
    harness = str(identity.get("executor") or "unknown")
    surface = str(identity.get("executor_surface") or harness)
    env["YOKE_EXECUTOR"] = harness
    roster_start = _roster_evidence(
        _run_json(run, ("sessions", "list", "--liveness", "active"), env).get(
            "rows", []
        )
    )
    started_at = datetime.now(timezone.utc)
    samples = []
    client_revisions: set[str] = set()
    server_revisions: set[str] = set()
    for ordinal in range(1, sample_count + 1):
        tool_use_id = f"hook-benchmark-{uuid.uuid4()}"
        payload = {
            "session_id": identity.get("session_id"),
            "cwd": os.getcwd(),
            "tool_name": "Bash",
            "tool_input": {"command": SAMPLE_COMMAND[0]},
            "tool_use_id": tool_use_id,
        }
        envelope_started = time.perf_counter_ns()
        pre_ms, pre = _run_hook(run, "PreToolUse", payload, env)
        command_started = time.perf_counter_ns()
        command = run(SAMPLE_COMMAND, capture_output=True, text=True, check=False)
        command_ms = max(0, int((time.perf_counter_ns() - command_started) / 1_000_000))
        if command.returncode != 0:
            raise BenchmarkRefusal(
                "HOOK_BENCHMARK_COMMAND_FAILED",
                f"{SAMPLE_COMMAND[0]} exited {command.returncode}",
                "restore the harmless system command and rerun",
            )
        post_payload = dict(payload)
        post_payload["tool_response"] = {"content": "Exit code 0"}
        post_ms, post = _run_hook(run, "PostToolUse", post_payload, env)
        envelope_ms = max(
            0, int((time.perf_counter_ns() - envelope_started) / 1_000_000)
        )
        for completed in (pre, post):
            provenance = parse_provenance(completed.stderr)
            if provenance["client_revision"]:
                client_revisions.add(str(provenance["client_revision"]))
            if provenance["server_revision"]:
                server_revisions.add(str(provenance["server_revision"]))
        samples.append(
            {
                "ordinal": ordinal,
                "pre_hook_ms": pre_ms,
                "command_ms": command_ms,
                "post_hook_ms": post_ms,
                "envelope_ms": envelope_ms,
                "pre_phase": None,
                "post_phase": None,
            }
        )
    ended_at = datetime.now(timezone.utc)
    dispatch_rows = _run_json(
        run,
        (
            "events",
            "query",
            "--event-name",
            "HookDispatchTelemetry",
            "--session",
            str(identity.get("session_id")),
            "--limit",
            str(sample_count * 2),
        ),
        env,
    ).get("rows", [])
    attach_durable_phases(samples, dispatch_rows)
    for sample in samples:
        phases = (sample.get("pre_phase"), sample.get("post_phase"))
        sample["status"] = (
            "complete"
            if all(
                isinstance(phase, dict)
                and isinstance(phase.get("evaluator_ms"), int)
                and isinstance(phase.get("client_wall_ms"), int)
                for phase in phases
            )
            else "incomplete"
        )
    roster_end = _roster_evidence(
        _run_json(run, ("sessions", "list", "--liveness", "active"), env).get(
            "rows", []
        )
    )
    summary = summarize_samples(samples)
    return {
        "schema": 1,
        "status": (
            "complete"
            if summary["client_wall_timing_coverage_pct"] == 100.0
            and summary["evaluator_timing_coverage_pct"] == 100.0
            else "incomplete"
        ),
        "harness": harness,
        "surface": surface,
        "client_revision": next(iter(client_revisions), None)
        if len(client_revisions) <= 1
        else "mixed",
        "server_revision": next(iter(server_revisions), None)
        if len(server_revisions) <= 1
        else "mixed",
        "time_window": {
            "started_at": started_at.isoformat(),
            "ended_at": ended_at.isoformat(),
        },
        "run_count": sample_count,
        "command": SAMPLE_COMMAND[0],
        "phase_definitions": {
            "pre_hook_ms": "wall time of normal PreToolUse policy evaluation",
            "command_ms": "wall time of the harmless system true command",
            "post_hook_ms": "wall time of normal PostToolUse policy evaluation",
            "envelope_ms": "PreToolUse start through PostToolUse completion",
            "evaluator_ms": (
                "HookDispatchTelemetry duration; local/admin execution may be "
                "in-process and is not uniformly server-only"
            ),
            "client_wall_ms": "hook process end to end from durable event context",
            "client_unattributed_ms": "client wall minus evaluator when both are timed",
        },
        "concurrency_evidence": {
            "definition": (
                "live roster counts sessions.list active rows; tool-active bucket "
                "proxy counts those rows whose turn_posture is running and does not "
                "prove simultaneous tool execution"
            ),
            "start": roster_start,
            "end": roster_end,
        },
        "summary": summary,
        "samples": samples,
    }


__all__ = [
    "BenchmarkRefusal",
    "attach_durable_phases",
    "compare_reports",
    "load_report",
    "parse_provenance",
    "run_benchmark",
    "summarize_samples",
]
