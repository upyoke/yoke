"""Adapter for listing the Actions runs of one exact commit."""

from __future__ import annotations

import argparse
from typing import List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    parse_or_usage_error,
    usage_error,
)
from yoke_cli.commands.adapters.github_actions_workflow import (
    _call,
    _emit_operation_error,
    _valid_repo,
)
from yoke_cli.transport.dispatcher import emit_response


GITHUB_ACTIONS_COMMIT_RUNS_USAGE = (
    "yoke github-actions commit-runs <commit-sha> [--workflow NAME] "
    "[--repo owner/name] --project P [--session-id S] [--json]"
)


def github_actions_commit_runs(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke github-actions commit-runs",
        description=(
            "List every GitHub Actions run whose head commit is exactly this "
            "sha. --workflow matches the workflow's own name, not a run's "
            "display title. --repo defaults to the project's bound repository."
        ),
    )
    parser.add_argument("commit_sha")
    parser.add_argument("--workflow", default="")
    parser.add_argument("--repo", default="")
    parser.add_argument("--project", required=True)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, GITHUB_ACTIONS_COMMIT_RUNS_USAGE)
    if parsed is None:
        return 2
    if parsed.repo and not _valid_repo(parsed.repo):
        return usage_error(f"repo must be owner/name, got {parsed.repo!r}")
    response = _call(
        "github_actions.commit_runs.list",
        {
            "project": parsed.project,
            "head_sha": parsed.commit_sha,
            **({"repo": parsed.repo} if parsed.repo else {}),
            **({"workflow": parsed.workflow} if parsed.workflow else {}),
        },
        session_id=parsed.session_id,
    )
    if not response.success:
        return _emit_operation_error(response, json_mode=parsed.json_mode)
    if parsed.json_mode:
        emit_response(response, json_mode=True)
        return 0
    for run in response.result.get("runs") or []:
        print(
            f"{run.get('id')} {run.get('name')} {run.get('status')} "
            f"{run.get('conclusion')} {run.get('html_url')}".rstrip()
        )
    return 0


__all__ = ["github_actions_commit_runs", "GITHUB_ACTIONS_COMMIT_RUNS_USAGE"]
