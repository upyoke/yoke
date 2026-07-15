"""CLI adapters for audited GitHub Actions config retirement."""

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


GITHUB_ACTIONS_SECRET_DELETE_USAGE = (
    "yoke github-actions secret delete <repo-slug> <secret-name> "
    "--project P [--session-id S] [--json]"
)
GITHUB_ACTIONS_VARIABLE_DELETE_USAGE = (
    "yoke github-actions variable delete <repo-slug> <variable-name> "
    "--project P [--session-id S] [--json]"
)


def github_actions_secret_delete(args: List[str]) -> int:
    return _config_delete(
        args, noun="secret", function_id="github_actions.secret.delete",
        usage=GITHUB_ACTIONS_SECRET_DELETE_USAGE,
    )


def github_actions_variable_delete(args: List[str]) -> int:
    return _config_delete(
        args, noun="variable", function_id="github_actions.variable.delete",
        usage=GITHUB_ACTIONS_VARIABLE_DELETE_USAGE,
    )


def _config_delete(
    args: List[str], *, noun: str, function_id: str, usage: str,
) -> int:
    parser = argparse.ArgumentParser(
        prog=f"yoke github-actions {noun} delete",
        description=(
            f"Delete one repo Actions {noun} through the project's bound "
            "GitHub App authority. Intended for audited post-window retirement."
        ),
    )
    parser.add_argument("repo", help="GitHub repo slug, e.g. upyoke/yoke.")
    parser.add_argument("name", help=f"Actions {noun} name.")
    parser.add_argument(
        "--project", required=True,
        help="Project capability owning the GitHub App repo binding.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, usage)
    if parsed is None:
        return 2
    if "/" not in parsed.repo:
        return usage_error(f"repo must be owner/name, got {parsed.repo!r}")
    return dispatch_and_emit(
        function_id=function_id,
        target=TargetRef(kind="global"),
        payload={"repo": parsed.repo, "name": parsed.name, "project": parsed.project},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


__all__ = [
    "GITHUB_ACTIONS_SECRET_DELETE_USAGE",
    "GITHUB_ACTIONS_VARIABLE_DELETE_USAGE",
    "github_actions_secret_delete",
    "github_actions_variable_delete",
]
