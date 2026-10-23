"""Registered CLI adapters for Performance's bounded event reads."""

from __future__ import annotations

import argparse

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
)
from yoke_contracts.api.function_call import TargetRef

_RANGE_USAGE = "--since ISO --until ISO [--project-ids ID,ID] [--points N]"
PERFORMANCE_AGGREGATE_USAGE = (
    f"yoke events performance aggregate {_RANGE_USAGE} [--full] [--session-id S] [--json]"
)
PERFORMANCE_DETAIL_USAGE = f"yoke events performance detail {_RANGE_USAGE} [--family FAMILY] [--offset N] [--limit N] [--full] [--session-id S] [--json]"


def _run(args: list[str], detail: bool) -> int:
    verb = "detail" if detail else "aggregate"
    usage = PERFORMANCE_DETAIL_USAGE if detail else PERFORMANCE_AGGREGATE_USAGE
    parser = argparse.ArgumentParser(
        prog=f"yoke events performance {verb}",
        usage=usage,
        description=(
            "Read the recorded operation timings between --since and --until; both\n"
            "timestamps need a timezone. If the range holds more timings than one\n"
            "read allows, the command refuses and returns nothing; shorten the range."
        ),
    )
    parser.add_argument(
        "--since",
        required=True,
        metavar="ISO",
        help="Start of the time range, as an ISO timestamp with a timezone.",
    )
    parser.add_argument(
        "--until",
        required=True,
        metavar="ISO",
        help="End of the time range, as an ISO timestamp with a timezone.",
    )
    parser.add_argument(
        "--project-ids",
        default=None,
        metavar="ID,ID",
        help="Comma-separated project ids to include; default: all projects.",
    )
    parser.add_argument(
        "--points",
        type=int,
        default=400,
        metavar="N",
        help="Number of points in the time series; default: 400.",
    )
    if detail:
        parser.add_argument(
            "--family",
            choices=["function", "tool", "hook", "relay", "watcher"],
            metavar="FAMILY",
            help="Kind of timing to read: function, tool, hook, relay, or watcher.",
        )
        parser.add_argument(
            "--offset",
            type=int,
            default=0,
            metavar="N",
            help="Rows to skip before the first one returned; default: 0.",
        )
        parser.add_argument(
            "--limit", type=int, default=50, metavar="N", help="Most rows returned; default: 50."
        )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, usage)
    if parsed is None:
        return 2
    payload = {"since": parsed.since, "until": parsed.until, "points": parsed.points}
    if parsed.project_ids is not None:
        try:
            payload["project_ids"] = [int(v) for v in parsed.project_ids.split(",")]
        except ValueError:
            parser.error("--project-ids must be comma-separated integer ids")
    if detail:
        payload.update(family=parsed.family, offset=parsed.offset, limit=parsed.limit)
    return dispatch_and_emit(
        function_id=f"events.performance.{verb}",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


def performance_aggregate(args: list[str]) -> int:
    return _run(args, False)


def performance_detail(args: list[str]) -> int:
    return _run(args, True)
