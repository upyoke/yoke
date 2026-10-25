"""Paged summary rows for the QA plan catalog."""

from __future__ import annotations

from yoke_cli.commands.adapters.list_paging import add_page_args, list_writer

import argparse

from yoke_cli.commands._helpers import (
    add_full_arg,
    add_json_arg,
    add_session_arg,
    detail_of,
    dispatch_and_emit,
    parse_or_usage_error,
)
from yoke_contracts.api.function_call import TargetRef


USAGE = (
    "yoke qa plan list --project P [--limit N] [--offset N] [--include-retired] "
    "[--full] [--session-id S] [--json]"
)


def qa_plan_list(args: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="yoke qa plan list", usage=USAGE)
    parser.add_argument(
        "--project", required=True, metavar="P", help="Project whose plans to list."
    )
    add_page_args(parser)
    parser.add_argument(
        "--include-retired",
        action="store_true",
        help=(
            "Also list retired plans, each with retired_at and "
            "retirement_reason (default: active plans only)."
        ),
    )
    add_full_arg(
        parser,
        "descriptions, attachments and execution targets for the same page",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, USAGE)
    if parsed is None:
        return 2
    payload = {
        "project": parsed.project,
        "limit": parsed.limit,
        "offset": parsed.offset,
        "detail": detail_of(parsed),
    }
    if parsed.include_retired:
        # Sent only when asked, so an active-only listing still reads from a
        # serving build that predates retired listing.
        payload["include_retired"] = True
    return dispatch_and_emit(
        function_id="qa.plan.list",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=list_writer("qa.plan.list"),
    )
