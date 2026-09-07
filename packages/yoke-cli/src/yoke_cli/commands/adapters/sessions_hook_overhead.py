"""``yoke sessions hook-overhead`` registered read adapter."""

from __future__ import annotations

import argparse
from typing import Any, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
)
from yoke_cli.commands.adapters.session_control_human_output import write_table
from yoke_contracts.api.function_call import TargetRef


SESSIONS_HOOK_OVERHEAD_USAGE = (
    "yoke sessions hook-overhead [--hours N] [--session-id S] [--json]"
)


def _cell(key: str):
    return lambda row: row.get(key)


def _coverage_cell(kind: str):
    def render(row):
        timed = row.get(f"{kind}_timed_count", 0)
        total = row.get("hook_count", 0)
        pct = row.get(f"{kind}_timing_coverage_pct", 0)
        return f"{timed}/{total} ({pct:.1f}%)"

    return render


def _surfaces(row):
    return ",".join(row.get("surfaces") or []) or "unreported"


def _tool_coverage(row):
    return (
        f"{row.get('timed_count', 0)}/{row.get('call_count', 0)} "
        f"({row.get('timing_coverage_pct', 0):.1f}%)"
    )


def sessions_hook_overhead(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke sessions hook-overhead",
        description=SESSIONS_HOOK_OVERHEAD_USAGE,
    )
    parser.add_argument("--hours", type=int, default=None)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, SESSIONS_HOOK_OVERHEAD_USAGE)
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        result = response.result or {}
        columns = (
            ("HOUR UTC", _cell("hour_utc"), 20),
            ("SCOPE", _cell("scope"), 8),
            ("HARNESS", _cell("harness"), 12),
            ("SURFACES", _surfaces, 16),
            ("HOOKS", _cell("hook_count"), 8),
            ("ACTIVE*", _cell("tool_active_session_count"), 8),
            ("CLIENT COV", _coverage_cell("client"), 18),
            ("EVAL COV", _coverage_cell("evaluator"), 18),
            ("STATUS", _cell("comparison_status"), 12),
            ("PRE C50", _cell("pre_client_p50_ms"), 9),
            ("POST C50", _cell("post_client_p50_ms"), 10),
            ("CALL", _cell("overhead_per_tool_call_ms"), 9),
        )
        write_table(
            "HOOK OVERHEAD (milliseconds)",
            columns,
            result.get("rows") or [],
            stdout,
            empty="No PreToolUse or PostToolUse telemetry found.",
        )
        if result.get("rows"):
            stdout.write(
                "\n* ACTIVE is distinct sessions emitting hook telemetry in the "
                "hour; it is a load proxy, not simultaneous-execution proof.\n"
            )
        tool_columns = (
            ("HOUR UTC", _cell("hour_utc"), 20),
            ("SCOPE", _cell("scope"), 8),
            ("HARNESS", _cell("harness"), 12),
            ("SURFACES", _surfaces, 16),
            ("CALLS", _cell("call_count"), 8),
            ("TIMING COVERAGE", _tool_coverage, 20),
            ("MEAN MS", _cell("mean_ms"), 10),
            ("P95 MS", _cell("p95_ms"), 10),
            ("ACTIVE*", _cell("tool_active_session_count"), 8),
            ("STATUS", _cell("comparison_status"), 12),
        )
        write_table(
            "TOOL LATENCY (milliseconds; missing durations excluded from latency)",
            tool_columns,
            result.get("tool_rows") or [],
            stdout,
            empty="No completed tool-call telemetry found.",
        )

    payload: dict[str, Any] = {}
    if parsed.hours is not None:
        payload["hours"] = parsed.hours
    return dispatch_and_emit(
        function_id="sessions.hook_overhead",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


__all__ = ["SESSIONS_HOOK_OVERHEAD_USAGE", "sessions_hook_overhead"]
