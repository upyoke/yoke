"""``yoke github-actions runners`` adapters."""

from __future__ import annotations

import argparse
from typing import Any, Dict, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
    usage_error,
)
from yoke_contracts.api.function_call import TargetRef


GITHUB_ACTIONS_RUNNERS_STATUS_USAGE = (
    "yoke github-actions runners status [repo-slug] "
    "[--required-label LABEL ...] [--variable-name NAME] "
    "--project P [--session-id S] [--json]"
)


def github_actions_runners_status(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke github-actions runners status",
        description=(
            "Read registered repository self-hosted runners. Optionally inspect "
            "an Actions variable containing the runs-on labels. Read-only."
        ),
    )
    parser.add_argument(
        "repo", nargs="?",
        help="GitHub repo slug; defaults to the project GitHub binding.",
    )
    parser.add_argument(
        "--required-label", action="append", default=[], dest="required_labels",
        help="Required runner label; repeatable. Defaults to self-hosted.",
    )
    parser.add_argument(
        "--variable-name", default="",
        help="Optional repository Actions variable to inspect for runs-on labels.",
    )
    parser.add_argument(
        "--project", required=True,
        help="Project capability owning the GitHub App repo binding.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser, args, GITHUB_ACTIONS_RUNNERS_STATUS_USAGE,
    )
    if parsed is None:
        return 2

    if parsed.repo and "/" not in parsed.repo:
        return usage_error(f"repo must be owner/name, got {parsed.repo!r}")

    labels = parsed.required_labels
    payload: Dict[str, Any] = {
        "repo": parsed.repo,
        "required_labels": labels,
        "variable_name": parsed.variable_name,
        "project": parsed.project,
    }
    return dispatch_and_emit(
        function_id="github_actions.runners.status",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


__all__ = [
    "GITHUB_ACTIONS_RUNNERS_STATUS_USAGE",
    "github_actions_runners_status",
]
