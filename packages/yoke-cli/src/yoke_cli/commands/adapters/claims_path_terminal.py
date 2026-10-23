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
        "--reason TEXT [--session-id S] [--json]"
    )


def _terminal(args: list[str], action: str) -> int:
    usage = terminal_usage(action)
    parser = argparse.ArgumentParser(
        prog=f"yoke claims path {action}",
        usage=usage,
        epilog=(
            "Requires the owning item's work claim. Release finished coverage; "
            "cancel abandoned coverage. Terminal claims cannot be reopened; "
            "register fresh coverage before editing reopened work."
        ),
    )
    parser.add_argument("--item", required=True, help="Owning item (PREFIX-N).")
    parser.add_argument("--claim-id", required=True, help="Path claim id.")
    parser.add_argument("--reason", required=True, help="Why coverage is ending.")
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
