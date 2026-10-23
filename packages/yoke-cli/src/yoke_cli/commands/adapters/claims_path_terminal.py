"""Holder-only release and cancellation of item-owned path claims."""

from __future__ import annotations

import argparse

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    item_target,
    parse_or_usage_error,
    usage_error,
)


def terminal_usage(action: str) -> str:
    return (
        f"yoke claims path {action} --item PREFIX-N --claim-id N "
        "--reason TEXT [--project P] [--session-id S] [--json]"
    )


def _terminal(args: list[str], action: str) -> int:
    usage = terminal_usage(action)
    parser = argparse.ArgumentParser(
        prog=f"yoke claims path {action}",
        usage=usage,
        epilog=(
            "You must hold the item's work claim. Use release when the work on\n"
            "those paths is finished and cancel when it is abandoned. A released\n"
            "or cancelled path claim cannot be reopened; record a new path claim\n"
            "before you edit those paths again."
        ),
    )
    parser.add_argument(
        "--item", required=True, metavar="PREFIX-N", help="The item that owns the path claim."
    )
    parser.add_argument("--claim-id", required=True, metavar="N", help="The path claim's id.")
    parser.add_argument(
        "--reason", required=True, metavar="TEXT", help="Why the path claim ends."
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, usage)
    if parsed is None:
        return 2
    try:
        claim_id = int(parsed.claim_id)
    except ValueError:
        return usage_error("--claim-id must be an integer path claim id")
    return dispatch_and_emit(
        function_id=f"claims.path.{action}",
        target=item_target("item", parsed.item, parsed.project),
        payload={"claim_id": claim_id, "reason": parsed.reason},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


def claims_path_release(args: list[str]) -> int:
    return _terminal(args, "release")


def claims_path_cancel(args: list[str]) -> int:
    return _terminal(args, "cancel")
