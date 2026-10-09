"""``yoke github-actions failed-log`` — every failed job of one CI run."""

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
from yoke_cli.commands.adapters.github_actions_full_log_capture import (
    capture_full_logs,
    render_captures,
)
from yoke_cli.transport.dispatcher import emit_response


GITHUB_ACTIONS_FAILED_LOG_USAGE = (
    "yoke github-actions failed-log <repo-slug> [<run-id>] "
    "[--workflow WORKFLOW] [--branch BRANCH] [--head-sha REF] "
    "[--lines N] [--full] --project P [--session-id S] [--json]"
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
            "Report every failed job of a workflow run via bearer-token REST "
            "(no host gh binary). Each failed job is read by its own job id "
            "as soon as it finishes, so a red shard is readable while "
            "sibling jobs keep the run in progress; the report says how many "
            "jobs are still running. Each failed job — every shard of a "
            "matrix included — gets its own labelled block carrying the job "
            "name, job id, conclusion, GitHub job URL, and its failure "
            "region: pytest's FAILURES section through the short test "
            "summary, else the step that raised the first ##[error], else "
            "the end of the log before teardown. Each region is bounded by "
            "--lines and an equal share of the report size, and every trim "
            "is named in place. --full also writes each failed job's "
            "complete log to a local file and prints its path. A job whose "
            "log GitHub cannot hand over (expired, missing, or permission "
            "denied) is still reported by name with that reason. Pass an "
            "explicit run id, or omit it and supply --workflow with optional "
            "--head-sha (default: resolved HEAD of the current checkout). "
            "--json adds the per-job structure alongside the report."
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
    parser.add_argument(
        "--lines",
        type=int,
        default=None,
        dest="max_lines",
        help=(
            "Most failure-region lines to show PER failed job (default: "
            "the server's bound, named in the report header whenever it "
            "trims). A pytest region keeps its first failure and its "
            "short test summary; other regions keep their end."
        ),
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help=(
            "Also write every failed job's complete log, untruncated, to a "
            "local file and print each path. The complete log downloads "
            "straight from GitHub, never through the bounded report."
        ),
    )
    parser.add_argument("--project", required=True)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, GITHUB_ACTIONS_FAILED_LOG_USAGE)
    if parsed is None:
        return 2
    if not _valid_repo(parsed.repo):
        return usage_error(f"repo must be owner/name, got {parsed.repo!r}")

    if parsed.max_lines is not None and parsed.max_lines < 1:
        return usage_error(f"--lines must be at least 1, got {parsed.max_lines}")
    payload: Dict[str, Any] = {"repo": parsed.repo, "project": parsed.project}
    if parsed.max_lines is not None:
        payload["max_lines"] = parsed.max_lines
    if parsed.full:
        payload["full"] = True
    if parsed.run_id:
        payload["run_id"] = parsed.run_id
    else:
        if not parsed.workflow:
            return usage_error(
                f"run id or --workflow is required: {GITHUB_ACTIONS_FAILED_LOG_USAGE}"
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
    if not parsed.full:
        if parsed.json_mode:
            return emit_response(response, json_mode=True)
        print(response.result.get("output") or "")
        return 0
    return _emit_with_full_logs(response, json_mode=parsed.json_mode)


def _emit_with_full_logs(response: Any, *, json_mode: bool) -> int:
    """Write every failed job's complete log, then report the files."""
    result = response.result
    jobs: List[Dict[str, Any]] = list(result.get("jobs") or [])
    if any("log_download_url" not in job for job in jobs):
        if not json_mode:
            print(result.get("output") or "")
        print(
            "error: full_log_capture_unsupported: this control plane returned "
            "no log_download_url. The report is current; complete capture "
            "requires a Yoke release carrying --full. Until upgraded, open "
            "each failed job's GitHub URL.",
            file=sys.stderr,
        )
        return 1
    captures = capture_full_logs(str(result.get("run_id") or ""), jobs)
    result["full_logs"] = [capture.__dict__ for capture in captures]
    if json_mode:
        emit_response(response, json_mode=True)
    else:
        print(result.get("output") or "")
        if captures:
            print()
            print(render_captures(captures, jobs))
    return 1 if any(not capture.path for capture in captures) else 0


__all__ = [
    "GITHUB_ACTIONS_FAILED_LOG_USAGE",
    "github_actions_failed_log",
]
