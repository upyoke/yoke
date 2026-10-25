"""Paged path-claim listing."""

from __future__ import annotations

import argparse
from typing import Any, Dict, List
from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    item_target,
    parse_or_usage_error,
    split_comma,
)
from yoke_cli.commands.adapters.list_paging import add_page_args, dispatch_list

CLAIMS_PATH_LIST_USAGE = (
    "yoke claims path list --item PREFIX-N [--state S]... [--project P] [--limit N] [--offset N] [--full] "
    "[--session-id S] [--json]"
)


def claims_path_list(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke claims path list",
        usage=CLAIMS_PATH_LIST_USAGE,
    )
    parser.add_argument(
        "--item",
        required=True,
        metavar="PREFIX-N",
        help="Item id (PREFIX-N).",
    )
    parser.add_argument(
        "--state",
        action="append",
        metavar="S",
        default=None,
        help=(
            "Filter by state (planned/blocked/active/released/cancelled); "
            "repeatable and/or comma-separated. Default: all states."
        ),
    )
    add_page_args(parser)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, CLAIMS_PATH_LIST_USAGE)
    if parsed is None:
        return 2
    states: List[str] = []
    for raw in parsed.state or []:
        states.extend(split_comma(raw))
    payload: Dict[str, Any] = {}
    if states:
        payload["states"] = states
    return dispatch_list(
        parsed=parsed,
        function_id="claims.path.list",
        target=item_target("item", parsed.item, parsed.project),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )
