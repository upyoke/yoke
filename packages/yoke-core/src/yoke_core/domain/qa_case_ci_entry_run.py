"""Prepare a CI lane and reuse a landing pull request's entry run.

A project whose branches land through the merge queue pays for its suite
three times when the gate dispatches a workflow run of its own: that
dispatch run, the ``pull_request`` run GitHub mints the moment the landing
pull request opens on the same tree, and the ``merge_group`` train run.
Only the last two are structural. GitHub's required checks take the latest
check run per name, so a dispatch green can never satisfy entry — the
adoption :mod:`yoke_core.domain.qa_case_ci_covering_run` already knows how
to do is reachable only when the pull-request run comes *first*.

Every live CI lane the gate still has to examine is brought current by
:mod:`yoke_core.domain.lane_base_update`, then the runner publishes it once. For merge-queue
projects the gate also opens the pull request and waits for the run that opening it produces. The landing
step later finds the same pull request open and green and simply enqueues
it. Per-item cost becomes one entry suite plus the train's amortized share.

Updating the base is safe before evidence exists, and tests the tree the
train will build; a candidate a run already covers has evidence, so
:mod:`yoke_core.domain.qa_case_ci_resume` keeps it off this step.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable, Optional

from yoke_core.domain import (
    authored_file_merge_preflight,
    lane_base_update,
    qa_case_ci_covering_run,
    qa_case_ci_lane,
    qa_case_ci_progress,
)
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


def prepare_ci_lane(
    checkout: Path,
    *,
    project: str,
    branch: str,
    lane_is_checked_out: bool,
) -> Optional[str]:
    """Update a live CI lane, then return its queue target when applicable.

    A recovered or recorded commit still takes the pull-request path when
    the project uses the queue, but cannot be rebased after its lane was
    released. ``None`` means this case keeps the dispatch path.
    """
    queue_routed = routes_through_merge_queue(project)
    if not lane_is_checked_out:
        return base_branch(project, checkout) if queue_routed else None
    target = base_branch(project, checkout)
    try:
        lane_base_update.bring_lane_current(
            checkout,
            branch=branch,
            target=target,
            project=project,
        )
    except lane_base_update.LaneBaseUpdateRefused as exc:
        raise QaCaseExecutionError(str(exc)) from exc
    if queue_routed:
        authored_file_merge_preflight.enforce_authored_file_limit(
            checkout, target=target
        )
        return target
    return None


def open_landing_pull_request(
    checkout: Path,
    *,
    project: str,
    branch: str,
    target: str,
    lane_head: str,
    public_ref: str = "",
) -> str:
    """Open (or converge on) the pull request whose entry run gates this tree.

    The lane branch identifies the pull-request head; the case's public item
    ref records which item owns it. Both verification and landing converge
    on that same head branch.

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

    ctx = lane_base_update.merge_context(
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
            item_public_ref=public_ref,
        )
    if error:
        raise QaCaseExecutionError(
            f"could not open the landing pull request for {branch!r}: {error}"
        )
    return pr_num


def find_entry_run(
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
    """Return the entry run for *head_sha* once it appears, or ``None``.

    The run is handed back in whatever state it is in. Whether that state
    means adopt a finished verdict or attach to a run still going is the
    caller's one decision for both routes
    (:mod:`yoke_core.domain.qa_case_ci_covering_run`), so this waits only
    for the run to exist.

    ``None`` means no pull-request run ever appeared for this commit,
    which the caller answers by dispatching — the same fallback it uses
    when a project has no pull request open at all.
    """
    deadline = monotonic() + ENTRY_RUN_APPEARANCE_TIMEOUT_SECONDS
    while True:
        run = qa_case_ci_covering_run.find_run_for_tree(
            project=project,
            repo=repo,
            workflow=workflow,
            head_sha=head_sha,
            timeout_seconds=timeout_seconds,
            event="pull_request",
        )
        if run is not None:
            return run
        if monotonic() >= deadline:
            return None
        qa_case_ci_progress.announce_covering_wait(
            requirement_id,
            repo=repo,
            head_sha=head_sha,
            next_poll_seconds=ENTRY_RUN_POLL_SECONDS,
        )
        sleep(ENTRY_RUN_POLL_SECONDS)


__all__ = [
    "ENTRY_RUN_APPEARANCE_TIMEOUT_SECONDS",
    "ENTRY_RUN_POLL_SECONDS",
    "base_branch",
    "find_entry_run",
    "open_landing_pull_request",
    "prepare_ci_lane",
    "routes_through_merge_queue",
]
