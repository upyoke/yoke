"""What a lane whose work already landed still owes its item.

The merge itself is durable by the time anything here runs, so this is
bookkeeping the caller's evidence and terminal transition read afterwards:
the ``merged_at`` stamp, a receipt naming the merge identity, and — when the
landing never reached origin because the process carrying it died first — the
push that publishes it. Whether the lane landed at all is a different question
with different reads, answered by
:mod:`yoke_core.domain.standalone_item_merge_landed`.

Nothing here re-merges, re-enters the queue, or publishes the lane branch. A
close-out that reaches this module has already been told the base branch holds
this lane's work, and the one way to make that false again is to land it twice.
"""

from __future__ import annotations

from yoke_core.domain import standalone_item_merge_git as git
from yoke_core.domain import item_merge_receipts as receipts
from yoke_core.domain.standalone_item_merge_landed import (
    LandedLane,
    stale_unlanded_work,
)
from yoke_core.engines.main_checkout_sync import fast_forward_main_checkout


def _converge_queue_landing(
    *,
    item_id: int,
    project: str,
    public_ref: str,
    repo_root: str,
    lane: LandedLane,
    queue_pr_number: str,
):
    """Finish the bookkeeping a two-call queue handoff deferred."""
    from yoke_core.domain.merge_queue_close_out import record_landing
    from yoke_core.domain.standalone_item_merge import StandaloneMergeOutcome
    from yoke_core.engines.merge_worktree_prepare import MergeArgs, MergeContext

    closed = record_landing(
        MergeContext(
            args=MergeArgs(branch=lane.branch, target=lane.target),
            repo_root=repo_root,
            project=project,
        ),
        item_id=item_id,
        commit_sha=lane.commit_sha,
        pr_num=queue_pr_number,
        member_snapshot=(public_ref,) if public_ref else (),
    )
    merge_sha = closed.merge_sha or lane.merge_sha or lane.commit_sha
    touched_files = closed.touched_files or lane.touched_files
    warnings = (
        f"branch {lane.branch!r} already landed on {lane.target!r}; "
        "queue bookkeeping converged without queue re-entry",
        *closed.warnings,
    )
    refusal = closed.ci_evidence_refusal(queue_pr_number)
    return StandaloneMergeOutcome(
        ok=not refusal,
        exit_code=0 if not refusal else 1,
        already_merged=True,
        commit_sha=lane.commit_sha,
        merge_sha=merge_sha,
        touched_files=touched_files,
        pushed=True,
        pr_num=queue_pr_number,
        error=refusal,
        warnings=warnings,
    )


def converge(
    *,
    item_id: int,
    project: str,
    repo_root: str,
    lane: LandedLane,
    queue_pr_number: str = "",
    public_ref: str = "",
):
    """Record what a lane that already landed still owes to its item."""
    stale = stale_unlanded_work(
        item_id=item_id,
        branch=lane.branch,
        target=lane.target,
        repo_root=repo_root,
        recorded_head=lane.commit_sha,
    )
    if stale:
        from yoke_core.domain.standalone_item_merge import StandaloneMergeOutcome

        return StandaloneMergeOutcome(
            ok=False,
            exit_code=1,
            already_merged=False,
            error=stale,
        )
    if queue_pr_number:
        return _converge_queue_landing(
            item_id=item_id,
            project=project,
            public_ref=public_ref,
            repo_root=repo_root,
            lane=lane,
            queue_pr_number=queue_pr_number,
        )

    from yoke_core.domain.standalone_item_merge import (
        StandaloneMergeOutcome,
        stamp_merged_at,
    )

    warnings = [
        f"branch {lane.branch!r} already landed on {lane.target!r} "
        f"({lane.source}); close-out converged without re-merging"
    ]
    merge_sha = lane.merge_sha or lane.commit_sha
    stamp_error = stamp_merged_at(item_id)
    if stamp_error:
        warnings.append(f"merged_at not recorded: {stamp_error}")
    receipt_note = receipts.record(
        item_id,
        receipts.MergeReceipt(
            branch=lane.branch,
            target=lane.target,
            commit_sha=lane.commit_sha,
            merge_sha=merge_sha,
            touched_files=lane.touched_files,
        ),
    )
    if receipt_note:
        warnings.append(receipt_note)

    pushed = False
    if git.has_remote(repo_root):
        git.fetch_target(repo_root, lane.target)
        if not git.is_ancestor(repo_root, lane.commit_sha, f"origin/{lane.target}"):
            pushed, push_warning = git.publish(repo_root, lane.target)
            if push_warning:
                warnings.append(push_warning)
        sync_warning = fast_forward_main_checkout(repo_root, lane.target)
        if sync_warning:
            warnings.append(sync_warning)
    return StandaloneMergeOutcome(
        ok=True,
        exit_code=0,
        already_merged=True,
        commit_sha=lane.commit_sha,
        merge_sha=merge_sha,
        touched_files=lane.touched_files,
        pushed=pushed,
        warnings=tuple(warnings),
    )


__all__ = ["converge"]
