"""Explicit activity pulse from a running watcher, separate from liveness."""

import argparse

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
)
from yoke_contracts.api.function_call import TargetRef

WATCHER_ACTIVITY_USAGE = "yoke sessions watcher-activity [--json] [--session-id S]"


def watcher_activity(args: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke sessions watcher-activity",
        description="Record work by a running watcher; ordinary liveness uses sessions touch.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, WATCHER_ACTIVITY_USAGE)
    if parsed is None:
        return 2
    return dispatch_and_emit(
        function_id="sessions.watcher_activity",
        target=TargetRef(kind="global"),
        payload={},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )
