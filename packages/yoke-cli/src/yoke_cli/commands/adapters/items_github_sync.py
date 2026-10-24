"""``yoke items github-sync`` adapter."""

from __future__ import annotations

import argparse
from typing import Any, Dict, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    item_target,
    parse_or_usage_error,
)


ITEMS_GITHUB_SYNC_USAGE = (
    "yoke items github-sync <PREFIX-N> [--session-id S] [--json] [--project P]"
)


def items_github_sync(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke items github-sync",
        description=(
            "Sync a backlog item or epic tasks to GitHub through the "
            "registered Yoke function surface."
        ),
    )
    parser.add_argument("item", help="Item id (PREFIX-N).")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, ITEMS_GITHUB_SYNC_USAGE)
    if parsed is None:
        return 2
    payload: Dict[str, Any] = {}
    return dispatch_and_emit(
        function_id="items.github_sync",
        target=item_target("item", parsed.item, parsed.project),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


__all__ = ["ITEMS_GITHUB_SYNC_USAGE", "items_github_sync"]


ITEMS_GITHUB_LINK_USAGE = (
    "yoke items github-link <PREFIX-N> (--issue "
    "NUMBER | --unlink) [--task-num N] [--json] "
    "[--session-id S] [--project P]"
)


def items_github_link(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke items github-link",
        description="Unlink or replace an item's GitHub issue link without editing either issue.",
        epilog="Claim the item first. The issue must exist in its bound repository. Unlink clears the link; the next GitHub sync may adopt an exact content match or create a new issue. Use --help for options.",
    )
    parser.add_argument("item", help="Item reference (PREFIX-N).")
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument(
        "--issue", type=int, help="Issue number to link in the project's repository."
    )
    choice.add_argument(
        "--unlink", action="store_true", help="Clear the stored issue link."
    )
    parser.add_argument(
        "--task-num", type=int, help="Repair one epic task instead of its parent item."
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, ITEMS_GITHUB_LINK_USAGE)
    if parsed is None:
        return 2
    return dispatch_and_emit(
        function_id="items.github_link",
        target=item_target("item", parsed.item, parsed.project),
        payload={"issue_number": parsed.issue, "task_num": parsed.task_num},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )
