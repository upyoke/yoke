"""``yoke qa post-deploy ...`` adapters."""

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

QA_POST_DEPLOY_DECLARE_NONE_USAGE = (
    "yoke qa post-deploy declare-none --item PREFIX-N "
    "(--reason TEXT | --content-file PATH | --stdin) [--project P] "
    "[--source operator|agent] [--session-id S] [--json]"
)

QA_POST_DEPLOY_DECLARE_NONE_EPILOG = """\
Records that this item needs no verification after its deploy, and why.

`yoke merge item` asks this question before the branch lands, while the
owner still holds the lane and the deploy has not happened. A recorded
declaration is a different artifact from an unanswered question: the
deployment QA stage lets the first through with no cases and holds the
second, so declaring is never the same as staying silent.

Use it only when there is genuinely nothing to check once the code is live.
An item that does have something to check attaches a plan instead, with
`yoke qa item-plan attach ... --qa-phase post_deploy`, which is durable and
resolves on every future deployment. Selecting a plan with `--plan` on a
running deployment stage is the third, different thing: it binds cases to
one run and writes nothing the next run will see.

The declaration is stored as this item's post-deploy requirement, waived
with your reason, so `waiver_rationale` carries the "because X" and the
usual QA reads show it. Repeating the command returns the declaration
already recorded rather than writing a second one.
"""


def qa_post_deploy_declare_none(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke qa post-deploy declare-none",
        description=QA_POST_DEPLOY_DECLARE_NONE_USAGE,
        epilog=QA_POST_DEPLOY_DECLARE_NONE_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--item", required=True, help="Item public ref.")
    parser.add_argument("--project", default=None, help="Item's project slug.")
    reason_group = parser.add_mutually_exclusive_group(required=True)
    add_text_file_pair(
        reason_group,
        "--reason",
        "--content-file",
        dest="reason",
        help_text="Why this item needs no post-deploy verification.",
        file_help="Read the reason from a path.",
    )
    add_stdin_flag(reason_group, help_text="Read the reason from stdin.")
    parser.add_argument(
        "--source",
        choices=("operator", "agent"),
        default="agent",
        help="Declaration authority source.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser, args, QA_POST_DEPLOY_DECLARE_NONE_USAGE
    )
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
        function_id="qa.post_deploy.declare_none",
        target=item_target("item", parsed.item, parsed.project),
        payload={"reason": reason, "source": parsed.source},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


USAGE_BY_FUNCTION_ID = {
    "qa.post_deploy.declare_none": QA_POST_DEPLOY_DECLARE_NONE_USAGE,
}

__all__ = [
    "QA_POST_DEPLOY_DECLARE_NONE_USAGE",
    "USAGE_BY_FUNCTION_ID",
    "qa_post_deploy_declare_none",
]
