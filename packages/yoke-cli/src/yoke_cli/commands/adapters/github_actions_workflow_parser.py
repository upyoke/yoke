"""Shared argument builders for the GitHub Actions workflow commands."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys

from yoke_cli.commands._helpers import add_json_arg, add_session_arg, usage_error

PROJECT_HELP = "Project capability owning the GitHub App repo binding."
INPUT_HELP = (
    "Workflow input as KEY=VALUE; repeat for each input. A nonempty sha "
    "must resolve to a commit in the current Git checkout."
)


def parse_workflow_inputs(raw_inputs: list[str]) -> dict[str, str]:
    inputs = {}
    for raw in raw_inputs:
        key, separator, value = raw.partition("=")
        if not separator or not key:
            raise ValueError(f"--input must be KEY=VALUE, got {raw!r}")
        inputs[key] = value
    if revision := inputs.get("sha"):
        inputs["sha"] = _resolve_sha(revision)
    return inputs


def _resolve_sha(revision: str) -> str:
    recovery = (
        f"cannot resolve --input sha={revision!r} to a commit. "
        "Run from the target repository checkout, fetch the commit, "
        "and retry with its full SHA."
    )
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", "--end-of-options",
             f"{revision}^{{commit}}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError(f"{recovery} Git lookup failed: {exc}") from exc
    commit = result.stdout.strip()
    if result.returncode or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError(recovery)
    return commit


def add_dispatch_wait_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--wait",
        type=int,
        metavar="SECONDS",
        help="Wait up to SECONDS for the exact run's terminal outcome.",
    )


def wait_for_dispatched_run(parsed: argparse.Namespace, run_id: str) -> int:
    from yoke_cli.commands.adapters.github_actions_run_wait import (
        wait_for_run_completion,
    )

    if not run_id:
        return usage_error("dispatch returned no run id; retry with the same --request-id")
    print(f"Waiting for GitHub Actions run {run_id}.", file=sys.stderr)
    return wait_for_run_completion(
        {"repo": parsed.repo, "run_id": run_id, "project": parsed.project},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        timeout_sec=parsed.wait,
    )



def add_workflow_args(parser: argparse.ArgumentParser, *, dispatch: bool) -> None:
    add = parser.add_argument
    add("repo", help="GitHub repo slug, e.g. upyoke/platform.")
    add("workflow", help="Workflow file name in .github/workflows.")
    if dispatch:
        add(
            "--ref",
            default="main",
            help="Git ref to run the workflow on; default: main.",
        )
        add("--input", action="append", dest="inputs", default=[], help=INPUT_HELP)


def add_common_args(parser: argparse.ArgumentParser, *, run_id: bool = False) -> None:
    parser.add_argument("repo", help="GitHub repo slug, e.g. upyoke/platform.")
    if run_id:
        parser.add_argument("run_id", help="GitHub Actions workflow run id.")
    parser.add_argument("--project", required=True, help=PROJECT_HELP)
    add_session_arg(parser)
    add_json_arg(parser)
