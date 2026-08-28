"""CLI adapters for holding a claim-free session alive, and releasing it."""

from __future__ import annotations

import argparse
from typing import Any, List, TextIO

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
)
from yoke_cli.commands.adapters.session_control_human_output import write_summary
from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.session_control.keepalive import (
    DEFAULT_KEEPALIVE_SECONDS,
    MAX_KEEPALIVE_SECONDS,
)


SESSION_KEEPALIVE_HOLD_USAGE = (
    "yoke sessions keepalive hold SESSION-ID --reason R "
    f"[--seconds N (default {DEFAULT_KEEPALIVE_SECONDS}, "
    f"max {MAX_KEEPALIVE_SECONDS})] [--json]"
)
SESSION_KEEPALIVE_RELEASE_USAGE = (
    "yoke sessions keepalive release SESSION-ID [--json]"
)

_HOLD_DESCRIPTION = (
    "Hold one live session against idle reaping until the lease expires. A "
    "session that holds no work claim, document lock, or chain budget is "
    "ended by the ordinary idle cleanup as soon as its turn stops; a hold "
    "says the emptiness is the point. Use it for a session that exists to be "
    "woken — a Fleet acceptance broker pair is the worked case. The hold is "
    "not a self-report: the held session's own tool calls neither set nor "
    "clear it, so it survives every turn the holder makes it take. Re-hold to "
    "extend. An explicit terminate, and a machine that proves the process is "
    "gone, still end the session."
)
_RELEASE_DESCRIPTION = (
    "Drop the keep-alive hold on one session, returning it to ordinary idle "
    "cleanup. Releasing a session that holds none is not an error."
)


def _write_hold_result(response: Any, stdout: TextIO, stderr: TextIO) -> None:
    del stderr
    result = response.result or {}
    write_summary(
        "SESSION KEEP-ALIVE",
        (
            ("SESSION", result.get("session_id")),
            ("HELD", bool(result.get("held"))),
            ("UNTIL", result.get("keepalive_until")),
            ("REASON", result.get("keepalive_reason")),
        ),
        stdout,
    )


def _write_release_result(response: Any, stdout: TextIO, stderr: TextIO) -> None:
    del stderr
    result = response.result or {}
    write_summary(
        "SESSION KEEP-ALIVE RELEASE",
        (
            ("SESSION", result.get("session_id")),
            ("RELEASED", bool(result.get("released"))),
        ),
        stdout,
    )


def session_keepalive_hold(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke sessions keepalive hold",
        usage=SESSION_KEEPALIVE_HOLD_USAGE,
        description=_HOLD_DESCRIPTION,
    )
    parser.add_argument("target_session_id", metavar="SESSION-ID")
    parser.add_argument("--reason", required=True)
    parser.add_argument(
        "--seconds", type=int, default=DEFAULT_KEEPALIVE_SECONDS
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, SESSION_KEEPALIVE_HOLD_USAGE)
    if parsed is None:
        return 2
    return dispatch_and_emit(
        function_id="session_control.keepalive.hold",
        target=TargetRef(kind="global"),
        payload={
            "session_id": parsed.target_session_id,
            "reason": parsed.reason,
            "seconds": parsed.seconds,
        },
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_write_hold_result,
    )


def session_keepalive_release(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke sessions keepalive release",
        usage=SESSION_KEEPALIVE_RELEASE_USAGE,
        description=_RELEASE_DESCRIPTION,
    )
    parser.add_argument("target_session_id", metavar="SESSION-ID")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, SESSION_KEEPALIVE_RELEASE_USAGE)
    if parsed is None:
        return 2
    return dispatch_and_emit(
        function_id="session_control.keepalive.release",
        target=TargetRef(kind="global"),
        payload={"session_id": parsed.target_session_id},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_write_release_result,
    )


__all__ = [
    "SESSION_KEEPALIVE_HOLD_USAGE",
    "SESSION_KEEPALIVE_RELEASE_USAGE",
    "session_keepalive_hold",
    "session_keepalive_release",
]
