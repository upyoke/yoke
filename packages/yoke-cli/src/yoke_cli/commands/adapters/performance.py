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


def _run(args: list[str], detail: bool) -> int:
    verb = "detail" if detail else "aggregate"
    usage = f"yoke events performance {verb} --since ISO --until ISO [--project-ids ID,ID] [--points N] [--json]"
    parser = argparse.ArgumentParser(
        prog=f"yoke events performance {verb}",
        description=(
            usage
            + ". Timestamps must carry a timezone. Reads retained timing observations; "
            "shorten the range if the observation budget refuses. No partial aggregate."
        ),
    )
    parser.add_argument("--since", required=True)
    parser.add_argument("--until", required=True)
    parser.add_argument("--project-ids", default=None)
    parser.add_argument("--points", type=int, default=400)
    if detail:
        parser.add_argument(
            "--family", choices=["function", "tool", "hook", "relay", "watcher"]
        )
        parser.add_argument("--offset", type=int, default=0)
        parser.add_argument("--limit", type=int, default=50)
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
