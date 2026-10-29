"""Session heartbeat mutation and its compact human receipt."""

from typing import Any, Dict, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
)
from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.session_queue_posture import SESSION_MODES

import argparse


SESSIONS_TOUCH_USAGE = (
    "yoke sessions touch [--mode MODE] [--reason TEXT] [--session-id S] [--json]"
)


def _write_touch_receipt(response, stdout, _stderr):
    session = response.result.get("session") or {}
    fields = [
        f"Session {session.get('session_id')}",
        f"mode: {session.get('mode')}",
        f"last heartbeat: {session.get('last_heartbeat')}",
    ]
    if session.get("quiet_reason"):
        fields.append(f"reason: {session['quiet_reason']}")
    print(" | ".join(" ".join(field.splitlines()) for field in fields), file=stdout)


def sessions_touch(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke sessions touch",
        usage=SESSIONS_TOUCH_USAGE,
    )
    parser.add_argument(
        "--mode",
        choices=sorted(SESSION_MODES),
        metavar="MODE",
        help="parked (with --reason) parks the session; wait unparks it.",
    )
    parser.add_argument(
        "--reason", metavar="TEXT", help="Why the session is parked."
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, SESSIONS_TOUCH_USAGE)
    if parsed is None:
        return 2
    payload: Dict[str, Any] = {}
    if parsed.mode is not None:
        payload["mode"] = parsed.mode
    if parsed.reason is not None:
        payload["reason"] = parsed.reason
    return dispatch_and_emit(
        function_id="sessions.touch",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_write_touch_receipt,
    )
