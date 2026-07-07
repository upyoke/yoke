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
    "yoke items github-sync <PREFIX-N> [--session-id S] [--json]"
)


def items_github_sync(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke items github-sync",
        description=(
            "Sync a backlog item or epic tasks to GitHub through the "
            "registered Yoke function surface."
        ),
    )
    parser.add_argument("item", help="Item id (PREFIX-N or project-local number).")
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
