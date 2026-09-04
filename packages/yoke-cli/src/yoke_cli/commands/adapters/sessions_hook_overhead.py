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
            ("HOOKS", _cell("hook_count"), 8),
            ("PRE C50", _cell("pre_client_p50_ms"), 9),
            ("PRE C90", _cell("pre_client_p90_ms"), 9),
            ("PRE S50", _cell("pre_server_p50_ms"), 9),
            ("PRE REM", _cell("pre_remainder_p50_ms"), 9),
            ("POST C50", _cell("post_client_p50_ms"), 10),
            ("POST C90", _cell("post_client_p90_ms"), 10),
            ("POST S50", _cell("post_server_p50_ms"), 10),
            ("POST REM", _cell("post_remainder_p50_ms"), 10),
            ("CALL", _cell("overhead_per_tool_call_ms"), 9),
        )
        write_table(
            "HOOK OVERHEAD (milliseconds)",
            columns,
            result.get("rows") or [],
            stdout,
            empty="No PreToolUse or PostToolUse telemetry found.",
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
