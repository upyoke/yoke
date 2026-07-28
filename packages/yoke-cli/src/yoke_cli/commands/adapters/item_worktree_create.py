"""``yoke item-worktrees create`` registered-function adapter."""

from __future__ import annotations

import argparse
import sys
from typing import List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    item_target,
    parse_or_usage_error,
)
from yoke_contracts.item_worktrees import (
    ADDITIONAL_ITEM_WORKTREE_LANE_ROLES,
)


_LANE_ROLE_USAGE = "|".join(ADDITIONAL_ITEM_WORKTREE_LANE_ROLES)
ITEM_WORKTREES_CREATE_USAGE = (
    "yoke item-worktrees create <PREFIX-N> "
    f"[--lane-role {_LANE_ROLE_USAGE} --branch BRANCH] "
    "[--project P] [--session-id S] [--json]"
)


def item_worktrees_create(args: List[str]) -> int:
    """Register one explicit additional lane for local provisioning."""
    parser = argparse.ArgumentParser(
        prog="yoke item-worktrees create",
        description=ITEM_WORKTREES_CREATE_USAGE,
    )
    parser.add_argument(
        "item",
        help="Item id (PREFIX-N or project-local number).",
    )
    parser.add_argument(
        "--lane-role",
        choices=ADDITIONAL_ITEM_WORKTREE_LANE_ROLES,
        help=(
            "Explicit additional lane role; omit with --branch to ensure the "
            "sole policy-required default lane."
        ),
    )
    parser.add_argument(
        "--branch",
        help="Exact explicit branch to register for local preparation.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, ITEM_WORKTREES_CREATE_USAGE)
    if parsed is None:
        return 2
    if bool(parsed.lane_role) != bool(parsed.branch):
        parser.print_usage(sys.stderr)
        print(
            "yoke item-worktrees create: error: --lane-role and --branch "
            "must be provided together",
            file=sys.stderr,
        )
        return 2

    def _human_writer(response, stdout, _stderr) -> None:
        worktree = (response.result or {}).get("worktree") or {}
        print(
            "item-worktree-created|"
            f"{worktree.get('id') or ''}|"
            f"{worktree.get('lane_role') or ''}|"
            f"{worktree.get('branch') or ''}|"
            f"{worktree.get('path') or ''}",
            file=stdout,
        )

    return dispatch_and_emit(
        function_id="item_worktrees.create",
        target=item_target("item", parsed.item, parsed.project),
        payload=(
            {
                "lane_role": parsed.lane_role,
                "branch": parsed.branch,
            }
            if parsed.lane_role else {}
        ),
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


__all__ = [
    "ITEM_WORKTREES_CREATE_USAGE",
    "item_worktrees_create",
]
