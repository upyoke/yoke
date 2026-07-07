"""GitHub Actions run monitoring command implementations."""

from __future__ import annotations

import sys
import time
from typing import Any, Callable, Dict, Optional

from yoke_core.domain.gh_rest_transport import (
    RestAuthError,
    RestTransportError,
)
from yoke_core.domain.github_actions_logs import fetch_failed_log

GetLatestRun = Callable[[], Optional[Dict[str, Any]]]
CheckAuth = Callable[[], None]
Sleep = Callable[[float], None]
FetchFailedLog = Callable[[str, str], Dict[str, str]]

# Canonical check-ci wait semantics, shared by the module CLI form and
# the ``yoke github-actions check-ci`` flag adapter's CLIENT-side wait
# loop. The ``github_actions.check_ci`` handler itself is single-shot
# because a server-side wait loop exceeds the https relay read timeout.
CHECK_CI_POLL_INTERVAL_SEC = 15
CHECK_CI_DEFAULT_TIMEOUT_SEC = 600
# How long ``--wait`` keeps polling a ``no_runs`` branch before accepting it.
# A just-pushed branch can briefly report ``no_runs`` while GitHub registers
# the triggered workflow run; waiting this long for the run to APPEAR closes
# the fail-open race where the gate skips CI it should have waited for. After
# this window ``no_runs`` is treated as genuine (branch runs no CI).
CHECK_CI_APPEARANCE_TIMEOUT_SEC = 90

__all__ = [
    "CHECK_CI_APPEARANCE_TIMEOUT_SEC",
    "CHECK_CI_DEFAULT_TIMEOUT_SEC",
    "CHECK_CI_POLL_INTERVAL_SEC",
    "check_ci_command",
    "failed_log_command",
]


def check_ci_command(
    repo: str,
    workflow: str,
    *,
    branch: str,
    wait: bool,
    timeout_sec: int,
    check_auth: CheckAuth,
    get_latest_run: GetLatestRun,
    now: Callable[[], float] = time.time,
    sleep: Sleep = time.sleep,
) -> None:
    """Check CI status on a branch and exit with the legacy CLI code."""
    check_auth()
    start = now()
    interval = CHECK_CI_POLL_INTERVAL_SEC

    while True:
        run = get_latest_run()
        if not run:
            print("no_runs")
            sys.exit(0)

        ci_id = run.get("id")
        if not ci_id:
            print("no_runs")
            sys.exit(0)

        ci_status = str(run.get("status") or "")
        ci_conclusion = str(run.get("conclusion") or "")
        ci_url = str(run.get("html_url") or "")

        if ci_status == "completed":
            if ci_conclusion == "success":
                print(f"passed|{ci_id}|{ci_url}")
                sys.exit(0)
            print(f"failed:{ci_conclusion}|{ci_id}|{ci_url}")
            sys.exit(1)

        if not wait:
            print(f"running:{ci_status}|{ci_id}|{ci_url}")
            sys.exit(2)

        elapsed = int(now() - start)
        if elapsed >= timeout_sec:
            print(f"timeout:{ci_status}|{ci_id}|{ci_url}")
            sys.exit(3)

        print(f"  CI status: {ci_status} (elapsed: {elapsed}s, timeout: {timeout_sec}s)", file=sys.stderr)
        sleep(interval)


def failed_log_command(
    repo: str,
    run_id: str,
    *,
    tail_lines: int,
    check_auth: CheckAuth,
    fetch_log: Optional[FetchFailedLog] = None,
) -> None:
    """Fetch a concise failed-step log tail and exit with legacy CLI code.

    Uses the REST ZIP-logs endpoint via :mod:`github_actions_logs` with
    automatic per-job fallback on ZIP 404. The ``fetch_log`` parameter
    exists as a test seam; production callers leave it ``None`` and the
    default :func:`github_actions_logs.fetch_failed_log` is invoked.
    """
    check_auth()

    fetch = fetch_log if fetch_log is not None else _default_fetch_log
    try:
        per_job = fetch(repo, run_id)
    except RestAuthError as exc:
        # Never log the token. RestAuthError.message carries only
        # HTTP status + body snippet (no Authorization header).
        print(
            f"Error: GitHub auth failure fetching logs for run {run_id}: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)
    except RestTransportError as exc:
        print(
            f"Error: failed to fetch logs for run {run_id}: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)

    log_text = _join_job_logs(per_job)
    if not log_text:
        print("(no failed-step output captured)", file=sys.stderr)
        sys.exit(1)

    lines = log_text.splitlines()
    if len(lines) > tail_lines:
        lines = lines[-tail_lines:]
        print(f"... (showing last {tail_lines} lines of failed-step output)")

    print("\n".join(lines))
    sys.exit(0)


def _default_fetch_log(repo: str, run_id: str) -> Dict[str, str]:
    """Production binding: resolve the project token + dispatch via REST.

    Kept private so the test seam in ``failed_log_command`` is the public
    monkeypatch point. The resolver is imported at call time to keep the
    module's import graph minimal and to let tests stub
    ``github_actions_rest.resolve_project_github_auth`` consistently
    with the sibling REST tests.
    """
    from yoke_core.domain.github_actions_rest import resolve_token

    token = resolve_token()
    return fetch_failed_log(repo, run_id, token=token)


def _join_job_logs(per_job: Dict[str, str]) -> str:
    """Join multiple job logs into one block for tail-trimming.

    The ZIP path's top-level entries carry per-step prefixes inline, so
    callers only need a stable separator between jobs. A blank line
    between sorted job blocks keeps the tail-trim deterministic when
    more than one job failed.
    """
    if not per_job:
        return ""
    blocks = []
    for name in sorted(per_job):
        body = per_job[name].strip("\n")
        if not body:
            continue
        blocks.append(body)
    return "\n\n".join(blocks).strip()
