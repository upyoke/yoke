"""Adapter for reading one branch's head through the project's binding."""

from __future__ import annotations

import argparse
from typing import List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
    usage_error,
)
from yoke_contracts.api.function_call import TargetRef


GITHUB_BRANCH_HEAD_USAGE = (
    "yoke github branch head <branch> [--since SHA] --project P "
    "[--session-id S] [--json]"
)


def _write_head(response, stdout, stderr) -> None:
    del stderr
    result = response.result or {}
    print(
        f"{result.get('head_sha')} {result.get('relation') or ''}".rstrip(), file=stdout
    )


def github_branch_head(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke github branch head",
        description=(
            "Print the commit a branch of the project's bound repository names "
            "now. --since takes a full commit sha and adds how the head relates "
            "to it: identical, descendant (the branch only moved forward), or "
            "not_descendant (the branch was rewritten or moved back)."
        ),
    )
    parser.add_argument("branch")
    parser.add_argument("--since", default="")
    parser.add_argument("--project", required=True)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, GITHUB_BRANCH_HEAD_USAGE)
    if parsed is None:
        return 2
    since = parsed.since.strip().lower()
    if since and (len(since) != 40 or any(c not in "0123456789abcdef" for c in since)):
        return usage_error(
            f"--since must be a full 40-hex commit, got {parsed.since!r}"
        )
    return dispatch_and_emit(
        function_id="github.branch.head",
        target=TargetRef(kind="global"),
        payload={
            "project": parsed.project,
            "branch": parsed.branch,
            **({"since": since} if since else {}),
        },
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_write_head,
    )


__all__ = ["github_branch_head", "GITHUB_BRANCH_HEAD_USAGE"]
