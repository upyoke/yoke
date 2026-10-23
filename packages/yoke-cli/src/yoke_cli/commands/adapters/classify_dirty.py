"""Classify a mapped project's dirty checkout on the caller's machine."""

from __future__ import annotations

import argparse

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
)
from yoke_contracts.api.function_call import TargetRef


USAGE = "yoke worktree classify-dirty --project PROJECT [--exclude-worktrees] [--json]"


def classify_dirty(args: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke worktree classify-dirty",
        description=(
            "Read the mapped checkout's managed and user-authored dirty files. "
            "Preserve user-authored files before merging; a refusal is not clean."
        ),
    )
    parser.add_argument("--project", required=True, help="Mapped project slug or id.")
    parser.add_argument(
        "--exclude-worktrees",
        action="store_true",
        help="Skip files inside the checkout's worktrees.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, USAGE)
    if parsed is None:
        return 2
    return dispatch_and_emit(
        function_id="worktree.classify_dirty",
        target=TargetRef(kind="global"),
        payload={
            "project": parsed.project,
            "exclude_worktrees": parsed.exclude_worktrees,
        },
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        local_only=True,
    )
