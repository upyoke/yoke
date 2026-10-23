"""Typed lifecycle transition CLI with stage-entry instruction delivery."""

from __future__ import annotations
import argparse
from typing import Any, Dict, List
from yoke_cli.commands._helpers import (
    add_session_arg,
    add_json_arg,
    parse_or_usage_error,
    dispatch_and_emit,
    item_target,
)
from yoke_cli.commands.adapters.workflow_execution_instructions import (
    write_transition_instructions,
)

LIFECYCLE_TRANSITION_USAGE = (
    "yoke lifecycle transition <PREFIX-N> --to STATUS "
    "[--from STATUS] [--reason TEXT] [--project P] [--session-id S] [--json]"
)


def lifecycle_transition(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke lifecycle transition",
        usage=LIFECYCLE_TRANSITION_USAGE,
    )
    parser.add_argument("item", metavar="PREFIX-N", help="Item to move.")
    parser.add_argument(
        "--to",
        dest="to_status",
        required=True,
        metavar="STATUS",
        help="Status to move the item to.",
    )
    parser.add_argument(
        "--from",
        dest="from_status",
        default=None,
        metavar="STATUS",
        help="Refuse unless the item's current status is this one.",
    )
    parser.add_argument(
        "--reason", default=None, metavar="TEXT", help="Why the item moves."
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, LIFECYCLE_TRANSITION_USAGE)
    if parsed is None:
        return 2
    payload: Dict[str, Any] = {"target_status": parsed.to_status}
    if parsed.from_status:
        payload["source_status"] = parsed.from_status
    if parsed.reason:
        payload["reason"] = parsed.reason
    return dispatch_and_emit(
        function_id="lifecycle.transition.execute",
        target=item_target("item", parsed.item, parsed.project),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=write_transition_instructions,
    )
