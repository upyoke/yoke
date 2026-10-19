"""GitHub Actions run cancellation adapter and cancellation-outcome lines."""

from __future__ import annotations

import argparse
from typing import Any, Mapping, TextIO

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
)
from yoke_contracts.api.function_call import TargetRef


GITHUB_ACTIONS_RUN_CANCEL_USAGE = (
    "yoke github-actions run cancel REPO RUN-ID --project P [--session-id S] [--json]"
)

_SETTLED_OUTCOMES = frozenset({"cancel_requested", "already_completed"})


def print_workflow_cancellation(
    entry: Mapping[str, Any], *, stdout: TextIO, stderr: TextIO
) -> None:
    """One line per workflow a closed run dispatched; unsettled ones on stderr."""
    outcome = str(entry.get("outcome") or "")
    run = str(entry.get("workflow_run_id") or "(unidentified)")
    line = f"Workflow {entry.get('repo', '')} run {run}: {outcome}"
    detail = str(entry.get("detail") or "")
    if outcome in _SETTLED_OUTCOMES:
        print(line, file=stdout)
    else:
        print(f"{line}: {detail}" if detail else line, file=stderr)


def github_actions_run_cancel(args: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke github-actions run cancel",
        description=(
            "Cancel one GitHub Actions run in the project's bound repository. "
            "Ordinary cancellation: the run's `if: cancelled()` steps still "
            "run. A run that already finished answers already_completed."
        ),
    )
    parser.add_argument("repo", help="Bound repository, owner/name.")
    parser.add_argument("run_id", help="GitHub Actions run id.")
    parser.add_argument(
        "--project", required=True, help="Project owning the repository binding."
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, GITHUB_ACTIONS_RUN_CANCEL_USAGE)
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        del stderr
        result = response.result or {}
        print(
            f"{result.get('repo', parsed.repo)} run "
            f"{result.get('run_id', parsed.run_id)}: {result.get('outcome', '')}",
            file=stdout,
        )

    return dispatch_and_emit(
        function_id="github_actions.run.cancel",
        target=TargetRef(kind="global"),
        payload={
            "repo": parsed.repo,
            "run_id": parsed.run_id,
            "project": parsed.project,
        },
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


__all__ = [
    "GITHUB_ACTIONS_RUN_CANCEL_USAGE",
    "github_actions_run_cancel",
    "print_workflow_cancellation",
]
