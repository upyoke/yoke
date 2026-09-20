"""``yoke qa item-plan retract`` adapter."""

from __future__ import annotations

import argparse
from typing import List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    item_target,
    parse_or_usage_error,
    usage_error,
)
from yoke_cli.commands.text_file import (
    add_stdin_flag,
    add_text_file_pair,
    resolve_one_text_source,
)


QA_ITEM_PLAN_RETRACT_USAGE = (
    "yoke qa item-plan retract --item PREFIX-N --project P --plan-id N "
    "--transition T (--reason TEXT | --content-file PATH | --stdin) "
    "[--source operator|agent] [--session-id S] [--json]"
)

QA_ITEM_PLAN_RETRACT_EPILOG = """\
Withdraw a standing item plan attachment that should not have been made.

The attachment row stays, marked retracted, so what was attached and why
it was withdrawn remain readable. Requirements it materialized retire as
retracted — not waived, not superseded. After retraction the item is
unanswered again: attach a corrected plan, or record that no post-deploy
obligation exists. Silence still blocks.

This path is for a mis-specified attachment, not an unwelcome verdict.
A verification-phase attachment cannot be retracted here. A post-deploy
case that already passed refuses, because that would rewrite settled
delivery evidence.
"""


def qa_plan_item_retract(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke qa item-plan retract",
        description=QA_ITEM_PLAN_RETRACT_USAGE,
        epilog=QA_ITEM_PLAN_RETRACT_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--item", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--plan-id", type=int, required=True)
    parser.add_argument("--transition", required=True)
    reason_group = parser.add_mutually_exclusive_group(required=True)
    add_text_file_pair(
        reason_group,
        "--reason",
        "--content-file",
        dest="reason",
        help_text="Why the attachment was mis-scoped.",
        file_help="Read the reason from a path.",
    )
    add_stdin_flag(reason_group, help_text="Read the reason from stdin.")
    parser.add_argument(
        "--source",
        choices=("operator", "agent"),
        default="agent",
        help="Retraction authority source.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, QA_ITEM_PLAN_RETRACT_USAGE)
    if parsed is None:
        return 2
    try:
        reason = resolve_one_text_source(
            positional=parsed.reason,
            file_path=parsed.reason_file,
            stdin=parsed.stdin,
            positional_label="--reason",
            file_flag="--content-file",
        )
    except ValueError as exc:
        return usage_error(str(exc))
    return dispatch_and_emit(
        function_id="qa.item_plan.retract",
        target=item_target("item", parsed.item, parsed.project),
        payload={
            "project": parsed.project,
            "plan_id": parsed.plan_id,
            "transition_id": parsed.transition,
            "reason": reason,
            "source": parsed.source,
        },
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


__all__ = [
    "QA_ITEM_PLAN_RETRACT_USAGE",
    "qa_plan_item_retract",
]
