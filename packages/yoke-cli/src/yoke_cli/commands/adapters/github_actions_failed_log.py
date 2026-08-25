"""``yoke github-actions failed-log`` — sanctioned CI failure-log read."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

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


GITHUB_ACTIONS_FAILED_LOG_USAGE = (
    "yoke github-actions failed-log <repo-slug> [<run-id>] "
    "[--workflow WORKFLOW] [--branch BRANCH] [--head-sha REF] "
    "[--tail-lines N] --project P [--session-id S] [--json]"
)


def _resolve_head_sha(head_ref: str) -> tuple[int, str]:
    """Resolve *head_ref* to a full commit id via local ``git rev-parse``.

    A CLI-local subprocess call (not an import of
    ``yoke_core.domain.github_actions_commit_run_watch.resolve_commit``)
    because client packages cannot take static authority over engine
    modules before the transport decision is made.
    """
    ref = head_ref or "HEAD"
    completed = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
        capture_output=True,
        text=True,
        cwd=str(Path.cwd()),
        check=False,
    )
    resolved = completed.stdout.strip()
    if completed.returncode != 0 or not resolved:
        print(f"error: '{ref}' does not name a commit in {Path.cwd()}", file=sys.stderr)
        return 2, ""
    return 0, resolved


def github_actions_failed_log(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke github-actions failed-log",
        description=(
            "Fetch failed-step log output for a workflow run via bearer-token "
            "REST (no host gh binary). Pass an explicit run id, or omit it "
            "and supply --workflow with optional --head-sha (default: "
            "resolved HEAD of the current checkout)."
        ),
    )
    parser.add_argument("repo")
    parser.add_argument("run_id", nargs="?", default=None)
    parser.add_argument(
        "--workflow",
        default=None,
        help="Workflow file when resolving the run from a commit selector.",
    )
    parser.add_argument("--branch", default="main")
    parser.add_argument(
        "--head-sha",
        default="",
        dest="head_sha",
        help="Commit to inspect (default: HEAD of the current checkout).",
    )
    parser.add_argument("--tail-lines", type=int, default=50, dest="tail_lines")
    parser.add_argument("--project", required=True)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, GITHUB_ACTIONS_FAILED_LOG_USAGE)
    if parsed is None:
        return 2
    if not _valid_repo(parsed.repo):
        return usage_error(f"repo must be owner/name, got {parsed.repo!r}")

    payload: Dict[str, Any] = {
        "repo": parsed.repo,
        "project": parsed.project,
        "tail_lines": parsed.tail_lines,
    }
    if parsed.run_id:
        payload["run_id"] = parsed.run_id
    else:
        if not parsed.workflow:
            return usage_error(
                "run id or --workflow is required: "
                f"{GITHUB_ACTIONS_FAILED_LOG_USAGE}"
            )
        payload["workflow"] = parsed.workflow
        payload["branch"] = parsed.branch
        head_ref = parsed.head_sha or "HEAD"
        rc, head_sha = _resolve_head_sha(head_ref)
        if rc != 0:
            return rc
        payload["head_sha"] = head_sha

    response = _call(
        "github_actions.failed_log",
        payload,
        session_id=parsed.session_id,
    )
    if not response.success:
        return _emit_operation_error(response, json_mode=parsed.json_mode)
    if parsed.json_mode:
        return emit_response(response, json_mode=True)
    print(response.result.get("output") or "")
    return 0


__all__ = [
    "GITHUB_ACTIONS_FAILED_LOG_USAGE",
    "github_actions_failed_log",
]
