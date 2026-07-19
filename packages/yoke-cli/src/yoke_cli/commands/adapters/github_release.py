"""Project-scoped immutable release-tag adapter."""

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


GITHUB_RELEASE_CREATE_NEXT_TAG_USAGE = (
    "yoke github release create-next-tag <repo-slug> <source-sha> "
    "--summary TEXT --project P [--session-id S] [--json]"
)
RELEASE_TAG_REQUEST_TIMEOUT_SECONDS = 120.0


def _write_created_tag(response, stdout, stderr) -> None:
    del stderr
    print(response.result.get("tag") or "", file=stdout)


def github_release_create_next_tag(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke github release create-next-tag",
        description=(
            "Create the next immutable annotated vX.Y.Z+launch.N tag on a "
            "main-reachable commit through the project's scoped GitHub App. "
            "A retry returns the existing tag for that same source commit."
        ),
    )
    parser.add_argument("repo", help="GitHub repo slug, e.g. upyoke/yoke.")
    parser.add_argument("source_sha", help="Full 40-character release commit SHA.")
    parser.add_argument(
        "--summary",
        required=True,
        help="Operator-facing summary stored in the annotated tag message.",
    )
    parser.add_argument(
        "--project",
        required=True,
        help="Project capability owning the GitHub App repo binding.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser,
        args,
        GITHUB_RELEASE_CREATE_NEXT_TAG_USAGE,
    )
    if parsed is None:
        return 2
    if "/" not in parsed.repo:
        return usage_error(f"repo must be owner/name, got {parsed.repo!r}")
    if len(parsed.source_sha) != 40:
        return usage_error("source-sha must be a full 40-character commit SHA")

    return dispatch_and_emit(
        function_id="github.release.create_next_tag",
        target=TargetRef(kind="global"),
        payload={
            "repo": parsed.repo,
            "project": parsed.project,
            "source_sha": parsed.source_sha,
            "summary": parsed.summary,
        },
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_write_created_tag,
        timeout_s=RELEASE_TAG_REQUEST_TIMEOUT_SECONDS,
    )


__all__ = [
    "GITHUB_RELEASE_CREATE_NEXT_TAG_USAGE",
    "RELEASE_TAG_REQUEST_TIMEOUT_SECONDS",
    "github_release_create_next_tag",
]
