"""Publish a lane commit, run its pytest selection on CI, adopt the verdict.

The engine behind :mod:`yoke_core.tools.pytest_remote_selection`. It runs as
its own process under the pytest watcher, so every line it prints is
classified and relayed the way a local pytest line would be: the run it
dispatched or rejoined, each ``Workflow status:`` transition, the tail of
the failed step's log when the run goes red, and the conclusion. The exit
status mirrors that conclusion, and every way the run can stop short of
one — an unpushable lane, a refused dispatch, a cancelled or timed-out run
— is named together with its recovery, because a silent green here would
be a green for tests that never ran.

Dispatch reuses the deployment layer's correlated workflow dispatch, which
replays a request id it has already seen. The request id is a function of
the commit and the selection, so a second invocation on the same tree
rejoins the run in flight rather than dispatching twice.
"""

from __future__ import annotations

import argparse
import shlex
import sys
from pathlib import Path
from typing import Sequence

from yoke_contracts.github_workflow_dispatch import (
    WORKFLOW_DISPATCH_CORRELATION_INPUT,
)
from yoke_core.tools.pytest_remote_selection import (
    EXIT_CANCELLED,
    EXIT_TIMED_OUT,
    EXIT_UNREACHABLE,
    LOCAL_FLAG,
    PREFIX,
)

#: Wall-clock ceiling for one selection run: queue wait, runner setup, and
#: a selection that is a small fraction of the suite.
DEFAULT_TIMEOUT_SECONDS = 1800
#: Lines of the failed step's log relayed into the local capture.
FAILED_LOG_TAIL_LINES = 150
#: How a run came to be the one this invocation reports on.
DISPATCHED = "dispatched"
REJOINED = "rejoined"
#: Exit status per GitHub conclusion; the process mirrors the run.
CONCLUSION_EXIT = {
    "success": 0,
    "failure": 1,
    "timed_out": EXIT_TIMED_OUT,
    "cancelled": EXIT_CANCELLED,
}


def _say(message: str) -> None:
    print(f"{PREFIX} {message}", flush=True)


def _error(message: str) -> None:
    print(f"Error: {PREFIX} {message}", flush=True)


def publish(root: Path, branch: str, head_sha: str) -> bool:
    """Push the lane so CI can check the commit out; False names the refusal."""
    from yoke_core.domain.qa_case_ci_lane import push_lane
    from yoke_core.domain.qa_case_execution import QaCaseExecutionError

    _say(f"publishing {branch}@{head_sha[:12]} to origin")
    try:
        push_lane(root, branch)
    except QaCaseExecutionError as exc:
        _error(
            f"push refused: {exc}. Fix the remote or credential, or re-run "
            f"with {LOCAL_FLAG}."
        )
        return False
    return True


#: The client transport prefixes its advisory hints with this and prints them
#: to stderr on any invocation. They are never the reason a call failed.
ADVISORY_LINE_PREFIX = "yoke: "


def failure_detail(result) -> str:
    """Why a dispatch failed, with the transport's advisory chatter removed.

    A build-skew hint shares stderr with the real diagnostic, and taking
    stderr whole reported "this checkout and the server's build have
    diverged" as the reason GitHub refused a dispatch — sending the reader
    after a version mismatch that had nothing to do with it.
    """
    for stream in (result.stderr, result.stdout):
        kept = [
            line
            for line in (stream or "").splitlines()
            if line.strip() and not line.startswith(ADVISORY_LINE_PREFIX)
        ]
        if kept:
            return "\n".join(kept).strip()
    return "no run id returned and no diagnostic on either stream"


def dispatch(
    *,
    project: str,
    repo: str,
    workflow: str,
    branch: str,
    head_sha: str,
    base_sha: str,
    pytest_args: Sequence[str],
    dispatch_id: str,
    timeout_seconds: int,
) -> tuple[str, str] | None:
    """Dispatch or rejoin the run; return ``(run_id, source)`` or None."""
    from yoke_core.domain.deploy_pipeline_github_workflow_dispatch import (
        trigger_with_recovery_retries,
    )
    from yoke_core.domain.deploy_pipeline_github_workflow_reconciliation import (
        _trigger_args,
        decode_trigger_result,
    )
    from yoke_core.domain.deploy_pipeline_reporting import _github_actions

    inputs = {
        "head_sha": head_sha,
        "base_sha": base_sha,
        "pytest_args": shlex.join(pytest_args),
    }
    args = _trigger_args(
        repo, workflow, branch, inputs,
        request_id=dispatch_id,
        correlation_input=WORKFLOW_DISPATCH_CORRELATION_INPUT,
    )
    result = trigger_with_recovery_retries(
        args,
        github_actions=_github_actions,
        project=project,
        sd=None,
        timeout_sec=timeout_seconds,
    )
    run_id, dispatched = decode_trigger_result(result)
    if result.returncode != 0 or not run_id:
        detail = failure_detail(result)
        _error(
            f"dispatch of {workflow} on {repo}@{branch} refused: {detail}. "
            f"Re-run with {LOCAL_FLAG} to test on this machine."
        )
        return None
    return run_id, (REJOINED if dispatched is False else DISPATCHED)


def await_conclusion(
    *, project: str, repo: str, run_id: str, timeout_seconds: int,
) -> str:
    """Poll the run to its end and name the conclusion GitHub reported."""
    from yoke_core.domain.deploy_pipeline_reporting import _poll_github_actions
    from yoke_core.domain.qa_case_ci_conclusion import conclusion_from_poll

    exit_code, output = _poll_github_actions(
        repo, run_id, timeout_seconds, project=project, sd=None,
    )
    conclusion = conclusion_from_poll(exit_code, output)
    if conclusion != "success" and output:
        print(output, flush=True)
    return conclusion


def relay_failed_log(*, project: str, repo: str, run_id: str) -> None:
    """Print the failed step's log tail so the FAILED lines reach the capture."""
    from yoke_core.domain.deploy_pipeline_reporting import _github_actions

    result = _github_actions(
        "failed-log", repo, run_id, "--tail-lines", str(FAILED_LOG_TAIL_LINES),
        project=project, timeout=180,
    )
    text = (result.stdout or "").strip()
    if result.returncode != 0 or not text:
        detail = (result.stderr or "").strip() or "no output"
        _say(
            f"failed-step log unavailable ({detail}); inspect with "
            f"`yoke github-actions failed-log {repo} {run_id} --project {project}`"
        )
        return
    print(text, flush=True)


def run(
    *,
    root: Path,
    project: str,
    workflow: str,
    repo: str,
    branch: str,
    head_sha: str,
    base_sha: str,
    pytest_args: Sequence[str],
    dispatch_id: str,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> int:
    """Publish, dispatch or rejoin, await, and mirror the conclusion."""
    if not publish(root, branch, head_sha):
        return EXIT_UNREACHABLE
    from yoke_core.domain.qa_case_ci_lane import github_actions_authority

    with github_actions_authority():
        started = dispatch(
            project=project,
            repo=repo,
            workflow=workflow,
            branch=branch,
            head_sha=head_sha,
            base_sha=base_sha,
            pytest_args=pytest_args,
            dispatch_id=dispatch_id,
            timeout_seconds=timeout_seconds,
        )
        if started is None:
            return EXIT_UNREACHABLE
        run_id, source = started
        url = f"https://github.com/{repo}/actions/runs/{run_id}"
        _say(
            f"{source} run={run_id} {url} head_sha={head_sha} "
            f"selection_base={base_sha or 'explicit paths'} "
            f"pytest_args={shlex.join(pytest_args) or '(none)'}"
        )
        conclusion = await_conclusion(
            project=project, repo=repo, run_id=run_id,
            timeout_seconds=timeout_seconds,
        )
        if conclusion != "success":
            relay_failed_log(project=project, repo=repo, run_id=run_id)
    exit_code = CONCLUSION_EXIT.get(conclusion, EXIT_UNREACHABLE)
    recovery = ""
    if conclusion not in ("success", "failure"):
        recovery = (
            "; the run reached no verdict — re-run the same command to "
            f"dispatch again, or re-run with {LOCAL_FLAG}"
        )
    _say(
        f"concluded {conclusion} exit={exit_code} run={run_id} {url} "
        f"ci_run_source={source}; full pytest output is the run's "
        f"pytest-output artifact{recovery}"
    )
    return exit_code


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pytest_remote_selection_run",
        description="Run one pytest selection on the project's CI.",
    )
    for name in ("root", "project", "workflow", "repo", "branch", "head-sha", "dispatch-id"):
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--base-sha", default="")
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("pytest_args", nargs=argparse.REMAINDER)
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    passthrough = list(args.pytest_args)
    if passthrough and passthrough[0] == "--":
        passthrough = passthrough[1:]
    return run(
        root=Path(args.root),
        project=args.project,
        workflow=args.workflow,
        repo=args.repo,
        branch=args.branch,
        head_sha=args.head_sha,
        base_sha=args.base_sha,
        pytest_args=passthrough,
        dispatch_id=args.dispatch_id,
        timeout_seconds=args.timeout_seconds,
    )


__all__ = [
    "CONCLUSION_EXIT",
    "DEFAULT_TIMEOUT_SECONDS",
    "DISPATCHED",
    "FAILED_LOG_TAIL_LINES",
    "REJOINED",
    "await_conclusion",
    "dispatch",
    "failure_detail",
    "main",
    "publish",
    "relay_failed_log",
    "run",
]


if __name__ == "__main__":  # pragma: no cover — exercised via subprocess
    raise SystemExit(main())
