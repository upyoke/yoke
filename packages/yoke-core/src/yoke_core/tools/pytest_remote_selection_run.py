"""Publish a lane commit, run its pytest selection on CI, adopt the verdict.

The engine behind :mod:`yoke_core.tools.pytest_remote_selection`. It runs as
its own process under the pytest watcher, so every line it prints is
classified and relayed the way a local pytest line would be: the run it
dispatched or rejoined, each ``Workflow status:`` transition, the tail of
every failed job's failure region when the run goes red, and the conclusion. The exit
status mirrors that conclusion, and every way the run can stop short of
one — an unpushable lane, a refused dispatch, a cancelled or timed-out run
— is named together with its recovery, because a silent green here would
be a green for tests that never ran.

Dispatch reuses the deployment layer's correlated workflow dispatch, which
replays a request id it has already seen. The request id is a function of
the commit and the selection, so a second invocation on the same tree
rejoins the run in flight rather than dispatching twice — unless that run
concluded with no verdict, which is re-dispatched instead.
"""

from __future__ import annotations

import argparse
import shlex
import sys
from pathlib import Path
from typing import Sequence

from yoke_core.domain.ci_job_outcome import CI_JOB_NOT_STARTED, REDISPATCH_RECOVERY
from yoke_core.tools.pytest_remote_selection import (
    EXIT_CANCELLED,
    EXIT_TIMED_OUT,
    EXIT_UNREACHABLE,
    LOCAL_FLAG,
    PREFIX,
)
from yoke_core.tools.pytest_remote_selection_report import (
    record_wait,
    relay_failed_log,
)
from yoke_core.tools.pytest_remote_selection_report import say as _say

#: Wall-clock ceiling for one selection run: queue wait, runner setup, and
#: a selection that is a small fraction of the suite.
DEFAULT_TIMEOUT_SECONDS = 1800
#: How a run came to be the one this invocation reports on.
DISPATCHED = "dispatched"
REJOINED = "rejoined"
#: Exit status per GitHub conclusion; the process mirrors the run.
CONCLUSION_EXIT = {
    "success": 0,
    "failure": 1,
    "timed_out": EXIT_TIMED_OUT,
    "cancelled": EXIT_CANCELLED,
    CI_JOB_NOT_STARTED: EXIT_CANCELLED,
}


def _error(message: str) -> None:
    print(f"Error: {PREFIX} {message}", flush=True)


def publish(
    root: Path,
    branch: str,
    head_sha: str,
    *,
    project: str,
    target: str,
) -> bool:
    """Push the lane so CI can check the commit out; False names the refusal.

    A lane whose pull request is still armed or queued is refused rather than
    pushed: the queue would land the head it already holds and this commit
    would land nowhere. That refusal carries its own recovery, so it is
    reported verbatim instead of under the remote/credential advice.
    """
    from yoke_core.domain.merge_queue_push_safety import LanePublishBlocked
    from yoke_core.domain.qa_case_ci_lane import push_lane
    from yoke_core.domain.qa_case_execution import QaCaseExecutionError

    _say(f"publishing {branch}@{head_sha[:12]} to origin")
    try:
        push_lane(root, branch, project=project, target=target)
    except LanePublishBlocked as exc:
        _error(str(exc))
        return False
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
    """Dispatch or rejoin the run; return ``(run_id, source)`` or None.

    A rejoined run that concluded with no verdict is re-dispatched rather
    than reported again (:mod:`yoke_core.domain.ci_run_redispatch`).
    """
    from yoke_core.domain.ci_run_redispatch import (
        RedispatchChainExhausted,
        dispatch_correlated,
    )

    inputs = {
        "head_sha": head_sha,
        "base_sha": base_sha,
        "pytest_args": shlex.join(pytest_args),
    }
    try:
        result, run_id, dispatched = dispatch_correlated(
            project=project,
            repo=repo,
            workflow=workflow,
            branch=branch,
            request_id=dispatch_id,
            timeout_seconds=timeout_seconds,
            inputs=inputs,
        )
    except RedispatchChainExhausted as exc:
        _error(str(exc))
        return None
    if result.returncode != 0 or not run_id:
        detail = failure_detail(result)
        _error(
            f"dispatch of {workflow} on {repo}@{branch} refused: {detail}. "
            f"Re-run with {LOCAL_FLAG} to test on this machine."
        )
        return None
    return run_id, (REJOINED if dispatched is False else DISPATCHED)


def await_conclusion(
    *,
    project: str,
    repo: str,
    run_id: str,
    timeout_seconds: int,
) -> str:
    """Poll the run to its end and name the conclusion GitHub reported."""
    from yoke_core.domain.deploy_pipeline_reporting import _poll_github_actions
    from yoke_core.domain.qa_case_ci_conclusion import conclusion_from_poll

    exit_code, output = _poll_github_actions(
        repo,
        run_id,
        timeout_seconds,
        project=project,
        sd=None,
    )
    conclusion = conclusion_from_poll(exit_code, output)
    if conclusion != "success" and output:
        print(output, flush=True)
    return conclusion


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
    continue_command: str = "",
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> int:
    """Publish, dispatch or rejoin, await, and mirror the conclusion."""
    from yoke_core.domain.qa_case_ci_entry_run import base_branch

    target = base_branch(project, root)
    if not publish(root, branch, head_sha, project=project, target=target):
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
        record_wait(
            repo=repo,
            run_id=run_id,
            head_sha=head_sha,
            continue_command=continue_command,
        )
        _say(
            f"{source} run={run_id} {url} head_sha={head_sha} "
            f"selection_base={base_sha or 'explicit paths'} "
            f"pytest_args={shlex.join(pytest_args) or '(none)'}"
        )
        conclusion = await_conclusion(
            project=project,
            repo=repo,
            run_id=run_id,
            timeout_seconds=timeout_seconds,
        )
        from yoke_core.domain.session_ci_wait_record import resolve_received_wait

        if warning := resolve_received_wait(run_id=run_id, conclusion=conclusion):
            _say(warning)
        if conclusion not in ("success", CI_JOB_NOT_STARTED):
            relay_failed_log(project=project, repo=repo, run_id=run_id)
    exit_code = CONCLUSION_EXIT.get(conclusion, EXIT_UNREACHABLE)
    recovery = ""
    if conclusion == CI_JOB_NOT_STARTED:
        recovery = f"; {REDISPATCH_RECOVERY}, or re-run with {LOCAL_FLAG}"
    elif conclusion not in ("success", "failure"):
        recovery = (
            "; the run reached no verdict — re-run the same command, which "
            f"dispatches a fresh run, or re-run with {LOCAL_FLAG}"
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
    for name in (
        "root",
        "project",
        "workflow",
        "repo",
        "branch",
        "head-sha",
        "dispatch-id",
    ):
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--base-sha", default="")
    parser.add_argument("--continue-command", default="")
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
        continue_command=args.continue_command,
        timeout_seconds=args.timeout_seconds,
    )


__all__ = [
    "CONCLUSION_EXIT",
    "DEFAULT_TIMEOUT_SECONDS",
    "DISPATCHED",
    "REJOINED",
    "await_conclusion",
    "dispatch",
    "failure_detail",
    "main",
    "publish",
    "run",
]


if __name__ == "__main__":  # pragma: no cover — exercised via subprocess
    raise SystemExit(main())
