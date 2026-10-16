"""Recover no-verdict required checks on the exact current PR head.

Use a full rerun when no job started, otherwise rerun failed/cancelled jobs.
Current-head, newest-run and bounded-attempt guards precede one POST per run.
Acceptance never proves admission: required checks must visibly be replaced.
A real failed job requires a lane correction rather than automatic recovery.
"""

from __future__ import annotations

import re
import time
from typing import Callable, Sequence

from yoke_contracts.designed_wait import announce_designed_wait, poll_every
from yoke_contracts.github_app_installation_permissions import (
    GITHUB_ACTIONS_WRITE_PERMISSION_LEVELS,
)
from yoke_contracts.api.function_call import HandlerOutcome
from yoke_core.domain.gh_rest_transport import RestTransportError, split_repo
from yoke_core.domain.github_actions_rest import rest_get, rest_post
from yoke_core.domain.github_actions_rerun_safety import checked_run
from yoke_core.domain.merge_queue_entry_checks import (
    describe_failed_checks,
    failed_required_checks,
)
from yoke_core.engines.merge_worktree_pr_check_runs import (
    LandingCheck,
    read_required_checks,
)
from yoke_core.engines.merge_worktree_pr_queue import resolve_auth_detail
from yoke_core.engines.merge_worktree_prepare import MergeContext

#: How long re-entry waits for the rollup to show the re-run checks.
REPLACED_CONFIRM_SECONDS = 60
REPLACED_READ_INTERVAL_SECONDS = 5

_RUN_ID_PATTERN = re.compile(r"/actions/runs/(\d+)")


def check_run_ids(checks: Sequence[LandingCheck]) -> tuple[str, ...]:
    """The distinct workflow runs behind *checks*, ``()`` if any has none."""
    run_ids: list[str] = []
    for check in checks:
        match = _RUN_ID_PATTERN.search(check.url or "")
        if match is None:
            return ()
        if match.group(1) not in run_ids:
            run_ids.append(match.group(1))
    return tuple(run_ids)


def redispatch_no_verdict_checks(
    ctx: MergeContext,
    pr_num: str,
    failed: Sequence[LandingCheck],
    *,
    read_checks: Callable[..., object] = read_required_checks,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.monotonic,
    lane_head: str = "",
) -> str:
    """Re-run *failed* on the same head; ``""`` once replaced, else a refusal.

    The caller has established that every check in *failed* is a
    no-verdict one. Each refusal names the checks, the reason, and the
    recovery.
    """
    names = describe_failed_checks(failed)
    run_ids = check_run_ids(failed)
    if not run_ids:
        return (
            f"pull request {pr_num} cannot enter the merge queue: its "
            f"required checks were cancelled or never started ({names}), but "
            "ci_recovery_run_missing: at least one names no GitHub Actions run. "
            "Ask the check provider to replace that exact-head check, verify "
            "its required-check verdict, then retry `yoke merge item`."
        )
    auth, auth_err = resolve_auth_detail(ctx, GITHUB_ACTIONS_WRITE_PERMISSION_LEVELS)
    if auth_err or auth is None:
        return (
            f"pull request {pr_num} cannot enter the merge queue: its "
            f"required checks were cancelled or never started ({names}) and "
            f"could not be re-run: {auth_err or 'github auth unavailable'}. "
            "Restore the project's GitHub Actions write access, then re-run "
            "`yoke merge item`"
        )
    owner, repo = split_repo(auth.repo)
    root = f"/repos/{owner}/{repo}"
    for run_id in run_ids:
        try:
            run = checked_run(
                root,
                pr_num,
                run_id,
                auth.token,
                expected_head=lane_head,
                allow_failure=False,
            )
            if isinstance(run, HandlerOutcome):
                return f"{run.error.code}: {run.error.message}"
            # Refresh after job inspection, immediately before the single POST.
            refreshed = checked_run(
                root,
                pr_num,
                run_id,
                auth.token,
                expected_head=run["head_sha"],
                allow_failure=False,
            )
            if isinstance(refreshed, HandlerOutcome):
                return f"{refreshed.error.code}: {refreshed.error.message}"
            if (run.get("run_attempt"), run["rerun_endpoint"]) != (
                refreshed.get("run_attempt"),
                refreshed["rerun_endpoint"],
            ):
                return "ci_rerun_attempt_changed: inspect the current run attempt and resume its CI wait; no rerun was sent."
            rest_post(
                f"{root}/actions/runs/{run_id}/{refreshed['rerun_endpoint']}",
                body={},
                token=auth.token,
                max_attempts=1,
            )
        except RestTransportError as exc:
            return (
                f"ci_recovery_unconfirmed: re-running run {run_id} for PR {pr_num} "
                f"({names}) could not be confirmed: {exc}. Inspect the run's "
                "attempt and status before any retry; the POST was not retried. "
                "Restore GitHub access if the safety reads failed."
            )
        lane_head = run["head_sha"]
    print(
        f"  Re-ran cancelled or never-started required checks ({names}) on "
        f"the same head via run(s) {', '.join(run_ids)}",
        flush=True,
    )
    announce_designed_wait(
        f"GitHub to replace the re-run required checks on PR #{pr_num}",
        max_wait_seconds=REPLACED_CONFIRM_SECONDS,
        cadence=poll_every(REPLACED_READ_INTERVAL_SECONDS),
        write=lambda line: print(f"  {line}", flush=True),
    )
    deadline = now() + REPLACED_CONFIRM_SECONDS
    while True:
        try:
            pr = rest_get(f"{root}/pulls/{pr_num}", token=auth.token)
        except RestTransportError as exc:
            return f"ci_recovery_identity_unavailable: {exc}. Restore GitHub PR reads and inspect the accepted attempt before retrying."
        if not isinstance(pr, dict) or (pr.get("head") or {}).get("sha") != lane_head:
            return "ci_recovery_head_changed: PR head changed or became unreadable after rerun; verify the current candidate and rerun its verification gate."
        checks, checks_error = read_checks(ctx, pr_num)
        if not checks_error and checks is not None:
            required = {check.name: check for check in checks if check.required}
            if all(
                name in required and not failed_required_checks((required[name],))
                for name in {check.name for check in failed}
            ):
                return ""
        if now() >= deadline:
            return (
                f"pull request {pr_num} cannot enter the merge queue: its "
                f"cancelled or never-started required checks ({names}) were "
                f"re-run via run(s) {', '.join(run_ids)}, but GitHub had not "
                f"replaced them within {REPLACED_CONFIRM_SECONDS}s. Re-run "
                "`yoke merge item` after inspecting the accepted attempt; active or "
                "superseded runs are never rerun automatically. A new declared "
                "workflow_dispatch is a fresh attempt: verify its exact head "
                "and required-check replacement."
            )
        sleep(REPLACED_READ_INTERVAL_SECONDS)


__all__ = [
    "REPLACED_CONFIRM_SECONDS",
    "check_run_ids",
    "redispatch_no_verdict_checks",
]
