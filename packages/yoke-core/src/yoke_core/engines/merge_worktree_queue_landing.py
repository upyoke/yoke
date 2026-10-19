"""Epic lane landing through the project's declared merge queue.

A project that declares the merge-queue capability lands each epic lane the
way it lands a single item (:mod:`yoke_core.domain.merge_queue_route`). The
queue retests the lane against the base branch as it stands when the train
forms, so other items landing while the lane's checks run cannot invalidate
its verification. A direct merge pinned to the base revision seen before CI
has to refuse whenever the base moves, and on a busy base that refusal
repeats on every retry.

The landing is recorded on the epic item exactly as a single item's is. An
epic whose earlier lane already landed records each later lane's pull request
as a re-land attempt, which the landing observer promotes when it merges.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from yoke_core.domain import standalone_item_merge_git as git
from yoke_core.domain.capability_undeclare_remedy import undeclare_remedy
from yoke_core.domain.merge_queue_landing_wait import RECOVERABLE_QUEUE_EXIT_CODE
from yoke_core.domain.merge_queue_route import land_item_through_merge_queue
from yoke_core.domain.merge_queue_route_selection import (
    project_declares_merge_queue,
)
from yoke_core.domain.projects_seed_ci_workflow import MERGE_QUEUE_CAPABILITY_TYPE
from yoke_core.domain.session_relay_launch_identity import (
    calling_session_is_relay_launched,
)
from yoke_core.engines.merge_worktree_context import MergeContext


@dataclass(frozen=True)
class QueueLaneLanding:
    """A queue project's lane landing: landed, or the exit that stops it.

    ``exit_code`` is ``None`` only when the lane is on the base branch and its
    queue close-out is recorded, so the caller's lane cleanup may proceed.
    """

    exit_code: Optional[int]
    pr_num: str = ""


def _print(line: str) -> None:
    from yoke_core.engines import merge_worktree as mw

    mw._print(line, err=True)


def resume_command(ctx: MergeContext) -> str:
    return (
        f"yoke watch merge merge-worktree -- {ctx.args.branch} "
        f"{ctx.args.target} {ctx.epic_id}"
    )


def queue_lane_landing(ctx: MergeContext) -> Optional[QueueLaneLanding]:
    """Land the lane through the queue; ``None`` when the project has none.

    A failing capability probe refuses rather than choosing the direct merge
    for a project that may have declared the queue.
    """
    declared, probe_error = project_declares_merge_queue(ctx.project or "")
    if probe_error:
        _print(
            f"merge_queue_probe_failed: {probe_error}. "
            + undeclare_remedy(
                MERGE_QUEUE_CAPABILITY_TYPE,
                project=ctx.project or "",
                consequence="epic lanes then land through a direct pull request merge",
            )
        )
        return QueueLaneLanding(exit_code=1)
    if not declared:
        return None
    lane_head = git.head_of(ctx.repo_root, ctx.args.branch)
    if not lane_head:
        _print(
            f"queue_lane_head_unresolved: branch '{ctx.args.branch}' does not "
            f"resolve in {ctx.repo_root}. Restore the lane branch and re-run "
            f"`{resume_command(ctx)}`."
        )
        return QueueLaneLanding(exit_code=1)
    outcome = land_item_through_merge_queue(
        ctx,
        public_ref=str(ctx.epic_id),
        commit_sha=lane_head,
        target=ctx.args.target,
        resume_command=resume_command(ctx),
        relay_launched=calling_session_is_relay_launched(),
    )
    for warning in outcome.warnings:
        _print(f"WARNING: {warning}")
    if not outcome.ok:
        _print(
            f"merge_queue_landing_refused: {outcome.error or 'queue landing failed'}"
        )
        return QueueLaneLanding(exit_code=outcome.exit_code or 1, pr_num=outcome.pr_num)
    if outcome.landing_pending:
        # The lane is armed, not landed. Exit 0 would let the caller land the
        # next lane and run its post-merge checks against a base that does not
        # hold this one yet.
        _print(
            f"landing_pending: pull request {outcome.pr_num} is in the merge "
            "queue. Wait for the landing notice, then re-run "
            f"`{resume_command(ctx)}` to record the landing and retire the lane."
        )
        return QueueLaneLanding(
            exit_code=RECOVERABLE_QUEUE_EXIT_CODE, pr_num=outcome.pr_num
        )
    return QueueLaneLanding(exit_code=None, pr_num=outcome.pr_num)


__all__ = ["QueueLaneLanding", "queue_lane_landing", "resume_command"]
