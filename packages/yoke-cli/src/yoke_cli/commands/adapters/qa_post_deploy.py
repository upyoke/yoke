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
Records a waiver that this item's post-deploy check is declined, and why.

This is the waiver-backed declaration: ``waived_at``, ``waiver_rationale``
and ``waiver_source`` carry a decision not to collect evidence. Use it when
there is something one might check once the code is live, and you are
choosing not to. An item that genuinely has no post-deploy obligation —
nothing about it is observable from outside once deployed — records that
fact with `yoke qa post-deploy record-no-obligation` instead. That command
is not a waiver, and an auditor listing waivers will not see it.

`yoke merge item` asks the emptiness question before the branch lands.
Silence is not an answer; a recorded no-obligation fact is. Repeating this
command returns the declaration already recorded rather than writing a
second one.
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
        help_text="Why this post-deploy check is being declined.",
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


QA_POST_DEPLOY_RECORD_NO_OBLIGATION_USAGE = (
    "yoke qa post-deploy record-no-obligation --item PREFIX-N "
    "(--reason TEXT | --content-file PATH | --stdin) [--project P] "
    "[--session-id S] [--json]"
)

QA_POST_DEPLOY_RECORD_NO_OBLIGATION_EPILOG = """\
Records that this item has no post-deploy obligation, and why.

Use it when nothing about the item is observable from outside once
deployed. That fact is not a waiver: a waiver says an obligation existed
and we chose not to satisfy it. `yoke qa post-deploy declare-none` remains
the waiver-backed declaration for declining a check that might have been
done.

`yoke merge item` asks this question before the branch lands. A recorded
no-obligation fact lets the deployment QA stage discharge with no cases
and no waiver row. Silence still blocks. An item that does have something
to check attaches a plan instead, with `yoke qa item-plan attach ...
--qa-phase post_deploy`. A mis-specified standing attachment is withdrawn
with `yoke qa item-plan retract` before this fact can be recorded.
Repeating this command returns the fact already recorded rather than
writing a second one.
"""


def qa_post_deploy_record_no_obligation(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke qa post-deploy record-no-obligation",
        description=QA_POST_DEPLOY_RECORD_NO_OBLIGATION_USAGE,
        epilog=QA_POST_DEPLOY_RECORD_NO_OBLIGATION_EPILOG,
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
        help_text="Why this item has no post-deploy obligation.",
        file_help="Read the reason from a path.",
    )
    add_stdin_flag(reason_group, help_text="Read the reason from stdin.")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser, args, QA_POST_DEPLOY_RECORD_NO_OBLIGATION_USAGE
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
        function_id="qa.post_deploy.record_no_obligation",
        target=item_target("item", parsed.item, parsed.project),
        payload={"reason": reason},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


USAGE_BY_FUNCTION_ID = {
    "qa.post_deploy.declare_none": QA_POST_DEPLOY_DECLARE_NONE_USAGE,
    "qa.post_deploy.record_no_obligation": (
        QA_POST_DEPLOY_RECORD_NO_OBLIGATION_USAGE
    ),
}

__all__ = [
    "QA_POST_DEPLOY_DECLARE_NONE_USAGE",
    "QA_POST_DEPLOY_RECORD_NO_OBLIGATION_USAGE",
    "USAGE_BY_FUNCTION_ID",
    "qa_post_deploy_declare_none",
    "qa_post_deploy_record_no_obligation",
]
