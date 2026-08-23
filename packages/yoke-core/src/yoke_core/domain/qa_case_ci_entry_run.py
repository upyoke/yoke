"""Make the landing pull request's entry run the verification gate's run.

A project whose branches land through the merge queue pays for its suite
three times when the gate dispatches a workflow run of its own: that
dispatch run, the ``pull_request`` run GitHub mints the moment the landing
pull request opens on the same tree, and the ``merge_group`` train run.
Only the last two are structural. GitHub's required checks take the latest
check run per name, so a dispatch green can never satisfy entry — the reuse
:func:`yoke_core.domain.qa_case_ci_lane.find_pull_request_run` already
knows how to do is reachable only when the pull-request run comes *first*.

So for those projects the gate opens the pull request itself and waits for
the run that opening it produces: rebase the lane onto the base branch,
push, open (or converge on) the landing pull request, and hand that entry
run back to the runner as the run whose conclusion is the verdict. The
landing step later finds the same pull request open and green and simply
enqueues it. Per-item cost becomes one entry suite plus the train's
amortized share.

Rebasing is free exactly here and nowhere later: no gate evidence has been
recorded yet, so nothing is invalidated, and the entry run then tests
approximately the tree the train will build — which is what keeps the queue
from bouncing it as out of date.
"""

from __future__ import annotations

import contextlib
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Optional

from yoke_core.domain import qa_case_ci_lane, qa_case_ci_progress
from yoke_core.domain.qa_case_execution import QaCaseExecutionError

#: How long to wait for GitHub to mint the entry run after the pull request
#: opens. Runs normally appear within seconds; the bound exists so a
#: workflow that never triggers falls back to a dispatch instead of holding
#: the whole case budget open.
ENTRY_RUN_APPEARANCE_TIMEOUT_SECONDS = 180

#: Gap between lookups while waiting for the entry run to appear.
ENTRY_RUN_POLL_SECONDS = 10.0


def routes_through_merge_queue(project: str) -> bool:
    """Whether *project* lands its item branches through the merge queue.

    A probe failure answers ``False``: the caller's fallback is the dispatch
    path the gate has always used, which verifies the same tree. That is a
    cost regression, never a correctness one, so an unreachable capability
    read must not fail the gate.
    """
    from yoke_core.domain.merge_queue_route_selection import (
        project_declares_merge_queue,
    )

    declared, _probe_error = project_declares_merge_queue(project)
    return bool(declared)


def base_branch(project: str, checkout: Path) -> str:
    """The branch this project's item branches land on."""
    from yoke_core.engines.done_transition_gates import (
        _get_base_branch,
        _resolve_default_branch,
    )

    return _get_base_branch(_resolve_default_branch(project), checkout) or "main"


def _git(checkout: Path, *args: str, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(checkout), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _merge_context(checkout: Path, *, branch: str, target: str, project: str):
    from yoke_core.engines.merge_worktree_prepare import MergeArgs, MergeContext

    return MergeContext(
        args=MergeArgs(branch=branch, target=target),
        repo_root=str(checkout),
        worktree_path=str(checkout),
        project=project,
    )


def rebase_lane_onto_base(
    checkout: Path,
    *,
    branch: str,
    target: str,
    project: str,
) -> None:
    """Replay the lane on top of ``origin/<target>`` before it is published.

    Uncommitted work goes through the merge engine's own safety-stash gate
    first, so nothing a rebase would disturb is unbacked; work the gate
    cannot classify as Yoke-managed stops the rebase rather than riding it.
    A lane that already contains the fetched base keeps its merge topology.
    Otherwise, a conflict aborts and surfaces the conflicted paths, because
    resolving them is the session's call — the same answer the landing gives
    when it cannot replay a branch on its own.
    """
    from yoke_core.engines.merge_worktree_prepare_state import (
        _stash_classify_gate,
    )

    ctx = _merge_context(
        checkout,
        branch=branch,
        target=target,
        project=project,
    )
    # The gate narrates to stdout, which here is the case runner's
    # machine-readable envelope; its narration belongs with the rest of the
    # run's human-readable output on stderr.
    with contextlib.redirect_stdout(sys.stderr):
        at_risk = _stash_classify_gate(ctx)
    if at_risk is not None:
        raise QaCaseExecutionError(
            f"lane {branch!r} carries uncommitted work that is not "
            f"Yoke-managed; it is backed up in stash "
            f"'yoke-pre-rebase-{branch}'. Commit it before running the gate "
            f"— the gate rebases the lane onto {target!r} and publishes it, "
            "so only committed work is verified."
        )
    fetched = _git(
        checkout,
        "fetch",
        "--quiet",
        "--no-tags",
        "origin",
        target,
        timeout=300,
    )
    if fetched.returncode != 0:
        detail = (fetched.stderr or fetched.stdout or "").strip()
        raise QaCaseExecutionError(
            f"could not fetch origin/{target} before rebasing {branch!r}: "
            f"{detail or 'fetch failed'}"
        )
    contains_base = _git(
        checkout,
        "merge-base",
        "--is-ancestor",
        f"origin/{target}",
        "HEAD",
    )
    if contains_base.returncode == 0:
        return
    if contains_base.returncode != 1:
        detail = (contains_base.stderr or contains_base.stdout or "").strip()
        raise QaCaseExecutionError(
            f"could not compare {branch!r} with origin/{target} before "
            f"rebasing: {detail or 'merge-base failed'}"
        )
    rebased = _git(checkout, "rebase", f"origin/{target}", timeout=600)
    if rebased.returncode == 0:
        return
    conflicts = _git(checkout, "diff", "--name-only", "--diff-filter=U")
    paths = tuple(conflicts.stdout.split())
    _git(checkout, "rebase", "--abort")
    detail = (
        ", ".join(paths)
        if paths
        else ((rebased.stderr or rebased.stdout or "").strip() or "rebase failed")
    )
    raise QaCaseExecutionError(
        f"rebasing {branch!r} onto origin/{target} conflicts: {detail}. "
        "Resolve the conflict on the lane and re-run the gate — the rebase "
        "happens before any gate evidence exists, so nothing is invalidated "
        "by redoing it."
    )


def prepare_entry_run_lane(
    checkout: Path,
    *,
    project: str,
    branch: str,
    lane_is_checked_out: bool,
) -> Optional[str]:
    """Return the base a queue project's landing pull request should target.

    A live lane is rebased onto that base first. A recovered or recorded
    commit still takes the pull-request path so the entry run is the
    verdict — dispatch is only for projects that do not land through the
    queue. ``None`` means this case keeps the dispatch path.
    """
    if not routes_through_merge_queue(project):
        return None
    target = base_branch(project, checkout)
    if lane_is_checked_out:
        rebase_lane_onto_base(
            checkout,
            branch=branch,
            target=target,
            project=project,
        )
    return target


def open_landing_pull_request(
    checkout: Path,
    *,
    project: str,
    branch: str,
    target: str,
    lane_head: str,
) -> str:
    """Open (or converge on) the pull request whose entry run gates this tree.

    The pull request is named for the lane branch because the case context
    carries no public item reference; the landing looks it up by head branch
    either way, so the two callers converge on the same pull request.

    Pull-request REST runs from this machine rather than through the
    Actions relay, so it needs this machine's own GitHub App user
    authorization — the same authority the merge boundary binds around the
    identical call. Control-plane App credentials are deliberately absent
    here; asking for them is what an unbound call falls through to.
    """
    from yoke_cli.commands.merge_item_local_runtime import (
        machine_github_user_authority,
    )
    from yoke_core.domain.merge_queue_landing_pull_request import (
        ensure_landing_pull_request,
    )

    ctx = _merge_context(
        checkout,
        branch=branch,
        target=target,
        project=project,
    )
    with machine_github_user_authority():
        pr_num, error = ensure_landing_pull_request(
            ctx,
            branch,
            lane_head=lane_head,
        )
    if error:
        raise QaCaseExecutionError(
            f"could not open the landing pull request for {branch!r}: {error}"
        )
    return pr_num


def await_entry_run(
    *,
    requirement_id: int,
    project: str,
    repo: str,
    workflow: str,
    head_sha: str,
    timeout_seconds: int,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> Optional[qa_case_ci_lane.WorkflowRun]:
    """Return the concluded entry run for *head_sha*, or ``None``.

    ``None`` means no pull-request run ever appeared for this commit, which
    the caller answers by dispatching — the same fallback it uses when a
    project has no pull request open at all.
    """
    deadline = monotonic() + ENTRY_RUN_APPEARANCE_TIMEOUT_SECONDS
    while True:
        run = qa_case_ci_lane.find_pull_request_run(
            project=project,
            repo=repo,
            workflow=workflow,
            head_sha=head_sha,
            timeout_seconds=timeout_seconds,
            status="",
        )
        if run is not None:
            break
        if monotonic() >= deadline:
            return None
        qa_case_ci_progress.announce_covering_wait(
            requirement_id,
            repo=repo,
            head_sha=head_sha,
            next_poll_seconds=ENTRY_RUN_POLL_SECONDS,
        )
        sleep(ENTRY_RUN_POLL_SECONDS)
    qa_case_ci_progress.announce_run(
        requirement_id,
        repo=repo,
        run_id=run.run_id,
        html_url=run.html_url,
        source="covering",
    )
    if run.status == "completed":
        return run
    qa_case_ci_lane.await_workflow(
        project=project,
        repo=repo,
        run_id=run.run_id,
        timeout_seconds=timeout_seconds,
    )
    return qa_case_ci_lane.find_pull_request_run(
        project=project,
        repo=repo,
        workflow=workflow,
        head_sha=head_sha,
        timeout_seconds=timeout_seconds,
        status="",
    )


__all__ = [
    "ENTRY_RUN_APPEARANCE_TIMEOUT_SECONDS",
    "ENTRY_RUN_POLL_SECONDS",
    "await_entry_run",
    "base_branch",
    "open_landing_pull_request",
    "prepare_entry_run_lane",
    "rebase_lane_onto_base",
    "routes_through_merge_queue",
]
