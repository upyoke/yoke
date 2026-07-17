"""GitHub Actions integration — trigger, poll, wait-run, find-run, check-ci, failed-log.

Every command resolves canonical project GitHub auth and verifies the requested
repository matches that binding;
``ProjectGithubAuthError`` surfaces as
``sys.exit(4)`` with the typed code + repair hint. No credential fallback.

All REST calls dispatch through :mod:`yoke_core.domain.gh_rest_transport` via
:mod:`yoke_core.domain.github_actions_rest` (workflow-run JSON) and
:mod:`yoke_core.domain.github_actions_logs` (failed-log ZIP bytes).
No host ``gh`` binary required.

Exit codes: 0 success, 1 failed/error, 2 waiting, 3 in-progress/timeout,
4 project GitHub auth failure.
"""

from __future__ import annotations

import sys
import time
from typing import Any, Dict, List, Optional

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_ACTIONS_READ_PERMISSION_LEVELS,
    GITHUB_ACTIONS_WRITE_PERMISSION_LEVELS,
)
from yoke_core.domain.gh_rest_transport import RestTransportError
from yoke_core.domain.github_actions_cli import build_parser as _build_parser
from yoke_core.domain.github_actions_rest import (
    adaptive_wait_interval,
    latest_workflow_run,
    resolve_token,
    rest_get,
    rest_post,
    run_state,
)
from yoke_core.domain.github_actions_run_monitoring import (
    check_ci_command,
    failed_log_command,
)


def cmd_trigger(
    repo: str,
    workflow: str,
    ref: str = "main",
    inputs: Optional[Dict[str, str]] = None,
    *,
    project: str,
) -> None:
    """Dispatch a workflow and print the new run ID. Exit 0=success / 1=error / 4=auth."""
    token = resolve_token(
        project,
        repo,
        required_permissions=GITHUB_ACTIONS_WRITE_PERMISSION_LEVELS,
    )
    payload: Dict[str, Any] = {"ref": ref, "return_run_details": True}
    if inputs:
        payload["inputs"] = dict(inputs)
    try:
        result = rest_post(
            f"/repos/{repo}/actions/workflows/{workflow}/dispatches",
            body=payload,
            token=token,
            max_attempts=1,
        )
    except RestTransportError as exc:
        print(
            f"Error: workflow dispatch failed for '{workflow}': {exc}",
            file=sys.stderr,
        )
        sys.exit(1)

    if not isinstance(result, dict) or not result.get("workflow_run_id"):
        print(
            "Error: workflow dispatch response omitted workflow_run_id",
            file=sys.stderr,
        )
        sys.exit(1)
    print(str(result["workflow_run_id"]))
    sys.exit(0)


def cmd_poll(repo: str, run_id: str, *, project: str) -> None:
    """Get run status. Exit 0=success / 1=failed / 2=waiting / 3=in_progress."""
    token = resolve_token(
        project,
        repo,
        required_permissions=GITHUB_ACTIONS_READ_PERMISSION_LEVELS,
    )
    exit_code, message = run_state(repo, run_id, token=token)
    output = sys.stderr if exit_code == 1 and message.startswith("Error:") else sys.stdout
    print(message, file=output)
    sys.exit(exit_code)


def cmd_jobs_count(
    repo: str, run_id: str, attempt: int = 1, *, project: str,
) -> None:
    """Print the total job count for a workflow run attempt. Exit 0 on
    success (prints the integer); exit 1 on REST failure.
    """
    token = resolve_token(
        project,
        repo,
        required_permissions=GITHUB_ACTIONS_READ_PERMISSION_LEVELS,
    )
    try:
        data = rest_get(
            f"/repos/{repo}/actions/runs/{run_id}/attempts/{attempt}/jobs",
            token=token,
        )
    except RestTransportError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    if not isinstance(data, dict) or "total_count" not in data:
        print(
            "Error: workflow jobs response omitted total_count",
            file=sys.stderr,
        )
        sys.exit(1)
    count = data.get("total_count")
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        print(
            "Error: workflow jobs total_count must be a non-negative integer",
            file=sys.stderr,
        )
        sys.exit(1)
    print(count)
    sys.exit(0)

def cmd_wait_run(
    repo: str,
    run_id: str,
    timeout_sec: int = 1800,
    *,
    project: str,
) -> None:
    """Wait for a terminal state. Exit 0=success / 1=failed / 3=timeout."""
    token = resolve_token(
        project,
        repo,
        required_permissions=GITHUB_ACTIONS_READ_PERMISSION_LEVELS,
    )

    start = time.monotonic()
    attempt = 0
    timeout_sec = max(0, timeout_sec)

    while True:
        exit_code, message = run_state(repo, run_id, token=token)
        if exit_code in (0, 1):
            output = sys.stderr if exit_code == 1 and message.startswith("Error:") else sys.stdout
            print(message, file=output)
            sys.exit(exit_code)

        elapsed = int(time.monotonic() - start)
        if elapsed >= timeout_sec:
            print(f"timeout:{message}")
            sys.exit(3)

        sleep_sec = min(adaptive_wait_interval(attempt), max(1, timeout_sec - elapsed))
        print(
            f"  Run status: {message} (elapsed: {elapsed}s, timeout: {timeout_sec}s)",
            file=sys.stderr,
        )
        time.sleep(sleep_sec)
        attempt += 1


def cmd_find_run(
    repo: str,
    workflow: str,
    commit_sha: str,
    *,
    project: str,
) -> None:
    """Find a run by commit SHA. Exit 0=found / 1=not_found."""
    token = resolve_token(
        project,
        repo,
        required_permissions=GITHUB_ACTIONS_READ_PERMISSION_LEVELS,
    )
    try:
        data = rest_get(
            f"/repos/{repo}/actions/workflows/{workflow}/runs",
            query={"head_sha": commit_sha, "per_page": "1"},
            token=token,
        )
    except RestTransportError as exc:
        print(
            f"Error: failed to find run for {commit_sha}: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)
    if not isinstance(data, dict):
        print(
            "Error: workflow-runs response must be an object",
            file=sys.stderr,
        )
        sys.exit(1)
    runs = data.get("workflow_runs")
    if not isinstance(runs, list):
        print(
            "Error: workflow-runs response omitted workflow_runs",
            file=sys.stderr,
        )
        sys.exit(1)
    if runs:
        first = runs[0]
        if not isinstance(first, dict) or first.get("id") in (None, ""):
            print(
                "Error: workflow-runs response contained a malformed run",
                file=sys.stderr,
            )
            sys.exit(1)
        print(str(first["id"]))
        sys.exit(0)
    print("not_found")
    sys.exit(1)


def cmd_check_ci(
    repo: str,
    workflow: str,
    branch: str = "main",
    head_sha: str = "",
    wait: bool = False,
    timeout_sec: int = 600,
    *,
    project: str,
) -> None:
    """Check CI on a branch and optional exact SHA."""
    token = resolve_token(
        project,
        repo,
        required_permissions=GITHUB_ACTIONS_READ_PERMISSION_LEVELS,
    )

    def _bound_latest_run() -> Optional[Dict[str, Any]]:
        return latest_workflow_run(
            repo, workflow, branch=branch, head_sha=head_sha, token=token,
        )

    try:
        check_ci_command(
            repo,
            workflow,
            branch=branch,
            wait=wait,
            timeout_sec=timeout_sec,
            check_auth=lambda: None,
            get_latest_run=_bound_latest_run,
            now=time.time,
            sleep=time.sleep,
        )
    except RestTransportError as exc:
        print(f"Error: CI check failed for '{workflow}': {exc}", file=sys.stderr)
        sys.exit(1)


def cmd_failed_log(
    repo: str,
    run_id: str,
    tail_lines: int = 50,
    *,
    project: str,
) -> None:
    """Fetch failed-step log tail. Exit 0=ok / 1=fail / 4=auth.

    Dispatches the run-logs ZIP endpoint via
    :mod:`yoke_core.domain.github_actions_logs`; per-job text fallback
    activates automatically when the ZIP endpoint 404s. Token resolution
    runs once here so the auth-failure exit code stays distinct from
    fetch failures inside the inner command.
    """
    token = resolve_token(
        project,
        repo,
        required_permissions=GITHUB_ACTIONS_READ_PERMISSION_LEVELS,
    )

    from yoke_core.domain.github_actions_logs import fetch_failed_log

    def _bound_fetch(_repo: str, _run_id: str) -> Dict[str, str]:
        return fetch_failed_log(_repo, _run_id, token=token)

    failed_log_command(
        repo,
        run_id,
        tail_lines=tail_lines,
        check_auth=lambda: None,
        fetch_log=_bound_fetch,
    )


def main(argv: Optional[List[str]] = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if not args.subcmd:
        parser.print_help(sys.stderr)
        sys.exit(1)

    if args.subcmd == "trigger":
        inputs_dict: Dict[str, str] = {}
        for inp in (args.inputs or []):
            k, _, v = inp.partition("=")
            inputs_dict[k] = v
        cmd_trigger(
            args.repo, args.workflow, ref=args.ref,
            inputs=inputs_dict or None, project=args.project,
        )

    elif args.subcmd == "poll":
        cmd_poll(args.repo, args.run_id, project=args.project)

    elif args.subcmd == "find-run":
        cmd_find_run(
            args.repo, args.workflow, args.commit_sha, project=args.project,
        )

    elif args.subcmd == "wait-run":
        cmd_wait_run(
            args.repo, args.run_id, timeout_sec=args.timeout_sec,
            project=args.project,
        )

    elif args.subcmd == "check-ci":
        cmd_check_ci(
            args.repo,
            args.workflow,
            branch=args.branch,
            head_sha=args.head_sha,
            wait=args.wait,
            timeout_sec=args.timeout_sec,
            project=args.project,
        )

    elif args.subcmd == "failed-log":
        cmd_failed_log(
            args.repo, args.run_id, tail_lines=args.tail_lines,
            project=args.project,
        )

    elif args.subcmd == "jobs-count":
        cmd_jobs_count(
            args.repo, args.run_id, attempt=args.attempt,
            project=args.project,
        )


if __name__ == "__main__":
    main()
