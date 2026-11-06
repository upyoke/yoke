"""Schedule a durable timed wake for the calling session."""

import argparse

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
)
from yoke_contracts.api.function_call import TargetRef

SCHEDULED_WAKE_USAGE = (
    "yoke sessions wake schedule --at INSTANT --reason TEXT [--session-id S] [--json]"
)


def sessions_wake_schedule(args: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke sessions wake schedule", usage=SCHEDULED_WAKE_USAGE
    )
    parser.add_argument(
        "--at", required=True, help="Earliest recheck instant, including UTC offset."
    )
    parser.add_argument(
        "--reason", required=True, help="Evidence to check when the wake arrives."
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, SCHEDULED_WAKE_USAGE)
    if parsed is None:
        return 2
    return dispatch_and_emit(
        function_id="sessions.wake.schedule",
        target=TargetRef(kind="global"),
        payload={"at": parsed.at, "reason": parsed.reason},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )
