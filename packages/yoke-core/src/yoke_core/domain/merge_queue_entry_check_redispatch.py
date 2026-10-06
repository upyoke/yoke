"""Re-run required checks that never reached a verdict on the same head.

A required check that was cancelled or never started — its job queued
until GitHub gave up on a runner — leaves the pull request unenqueueable,
yet it says nothing about the head. Re-entering ``yoke merge item`` used to
refuse the same cancelled set again, because nothing ever re-ran it; the
only way out was a new commit, which also invalidated every verdict bound
to the old one.

So merge re-entry re-runs those checks' workflow runs on the exact head
(GitHub's ``rerun-failed-jobs``, which re-runs the failed and cancelled
jobs of the run) and arms only once the rollup shows them replaced. A set
holding any real red check is never re-run: red is an answer about the
head, and its recovery stays a fix on the lane.
"""

from __future__ import annotations

import re
import time
from typing import Callable, Sequence

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_ACTIONS_WRITE_PERMISSION_LEVELS,
)
from yoke_core.domain.gh_rest_transport import (
    RestRequest,
    RestTransportError,
    request_with_retry,
    split_repo,
)
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
            f"pull request {pr_num} was not armed for the merge queue: its "
            f"required checks were cancelled or never started ({names}), but "
            "at least one names no GitHub Actions run to re-run. Re-run that "
            "check from the pull request's Checks tab, then re-run "
            "`yoke merge item`"
        )
    auth, auth_err = resolve_auth_detail(ctx, GITHUB_ACTIONS_WRITE_PERMISSION_LEVELS)
    if auth_err or auth is None:
        return (
            f"pull request {pr_num} was not armed for the merge queue: its "
            f"required checks were cancelled or never started ({names}) and "
            f"could not be re-run: {auth_err or 'github auth unavailable'}. "
            "Restore the project's GitHub Actions write access, then re-run "
            "`yoke merge item`"
        )
    owner, repo = split_repo(auth.repo)
    for run_id in run_ids:
        try:
            request_with_retry(
                RestRequest(
                    method="POST",
                    path=f"/repos/{owner}/{repo}/actions/runs/{run_id}/rerun-failed-jobs",
                    body={},
                ),
                token=auth.token,
            )
        except RestTransportError as exc:
            return (
                f"pull request {pr_num} was not armed for the merge queue: "
                f"re-running run {run_id} for its cancelled or never-started "
                f"required checks ({names}) failed: {exc}. Re-run "
                "`yoke merge item` to try again"
            )
    print(
        f"  Re-ran cancelled or never-started required checks ({names}) on "
        f"the same head via run(s) {', '.join(run_ids)}",
        flush=True,
    )
    deadline = now() + REPLACED_CONFIRM_SECONDS
    while True:
        checks, checks_error = read_checks(ctx, pr_num)
        if not checks_error and checks is not None:
            still_red = {check.name for check in failed_required_checks(checks)}
            if not still_red & {check.name for check in failed}:
                return ""
        if now() >= deadline:
            return (
                f"pull request {pr_num} was not armed for the merge queue: its "
                f"cancelled or never-started required checks ({names}) were "
                f"re-run via run(s) {', '.join(run_ids)}, but GitHub had not "
                f"replaced them within {REPLACED_CONFIRM_SECONDS}s. Re-run "
                "`yoke merge item`; it arms once the re-run checks appear"
            )
        sleep(REPLACED_READ_INTERVAL_SECONDS)


__all__ = [
    "REPLACED_CONFIRM_SECONDS",
    "check_run_ids",
    "redispatch_no_verdict_checks",
]
