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
from yoke_contracts.github_actions_runner_fleet import (
    CAPABILITY_TYPE as RUNNER_FLEET_CAPABILITY_TYPE,
    DEFAULT_RUNS_ON_VARIABLE,
)
from yoke_contracts.api.function_call import TargetRef


GITHUB_ACTIONS_RUNNERS_STATUS_USAGE = (
    "yoke github-actions runners status [repo-slug] "
    "[--required-label LABEL ...] [--variable-name NAME] "
    "[--runner-capability TYPE] --project P [--session-id S] [--json]"
)


def github_actions_runners_status(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke github-actions runners status",
        description=(
            "Read registered repository self-hosted runners and the "
            "runner-routing repo variable before arming workflows. "
            "Read-only; does not mint runner registration tokens and "
            "does not mutate GitHub repo variables."
        ),
    )
    parser.add_argument(
        "repo", nargs="?",
        help=(
            "GitHub repo slug, e.g. upyoke/yoke. Omit to read it from "
            "the runner fleet capability."
        ),
    )
    parser.add_argument(
        "--required-label",
        action="append",
        default=[],
        dest="required_labels",
        help=(
            "Runner label required for the workflow route. Repeatable. "
            "Defaults to the runner fleet capability labels, or "
            "self-hosted, Linux, ARM64, yoke-github-actions when the "
            "capability is absent."
        ),
    )
    parser.add_argument(
        "--variable-name",
        default="",
        help=(
            "Repo variable to inspect. Defaults to the runner fleet "
            f"capability value, or {DEFAULT_RUNS_ON_VARIABLE} when the "
            "capability is absent."
        ),
    )
    parser.add_argument(
        "--runner-capability",
        default=RUNNER_FLEET_CAPABILITY_TYPE,
        help=(
            "Project capability type holding runner fleet settings "
            f"(default: {RUNNER_FLEET_CAPABILITY_TYPE})."
        ),
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
        "runner_capability": parsed.runner_capability,
    }
    return dispatch_and_emit(
        function_id="github_actions.runners.status",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        local_only=True,
    )


__all__ = [
    "GITHUB_ACTIONS_RUNNERS_STATUS_USAGE",
    "github_actions_runners_status",
]
