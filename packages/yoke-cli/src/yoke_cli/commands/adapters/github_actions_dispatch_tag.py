"""``yoke github-actions dispatch-tag ensure`` adapter."""

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


GITHUB_ACTIONS_DISPATCH_TAG_ENSURE_USAGE = (
    "yoke github-actions dispatch-tag ensure <repo-slug> <tag> <commit-sha> "
    "--project P [--session-id S] [--json]"
)


def github_actions_dispatch_tag_ensure(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke github-actions dispatch-tag ensure",
        description=(
            "Create the lightweight yoke-deploy/<run-id> tag a deployment "
            "stage declaring run_from_release_commit is dispatched at, or "
            "confirm it already names the commit. Refuses a tag outside the "
            "yoke-deploy/ namespace, a commit the repository does not hold, "
            "and an existing tag naming another commit (never moved)."
        ),
    )
    parser.add_argument("repo", help="GitHub repo slug, e.g. upyoke/platform.")
    parser.add_argument("tag", help="Dispatch tag, e.g. yoke-deploy/run-20261007-021.")
    parser.add_argument("sha", help="Full 40-character commit the tag names.")
    parser.add_argument(
        "--project", required=True,
        help="Project whose GitHub App binding authorizes the write.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser, args, GITHUB_ACTIONS_DISPATCH_TAG_ENSURE_USAGE,
    )
    if parsed is None:
        return 2
    if "/" not in parsed.repo:
        return usage_error(f"repo must be owner/name, got {parsed.repo!r}")
    return dispatch_and_emit(
        function_id="github_actions.dispatch_tag.ensure",
        target=TargetRef(kind="global"),
        payload={
            "repo": parsed.repo,
            "project": parsed.project,
            "tag": parsed.tag,
            "sha": parsed.sha,
        },
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


__all__ = [
    "GITHUB_ACTIONS_DISPATCH_TAG_ENSURE_USAGE",
    "github_actions_dispatch_tag_ensure",
]
