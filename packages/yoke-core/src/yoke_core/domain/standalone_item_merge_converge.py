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

from yoke_core.domain import item_merge_contributed_commits as contributed
from yoke_core.domain import standalone_item_merge_git as git
from yoke_core.domain import item_merge_receipts as receipts
from yoke_core.domain.merge_landing_proof import (
    LandingUnverified,
    verified_landing_identity,
    verified_target_sha,
)
from yoke_core.domain.standalone_item_merge_landed import LandedLane
from yoke_core.domain.standalone_item_merge_stale_lane import stale_unlanded_work
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
    from yoke_core.domain.merge_queue_landed_candidate import (
        landed_candidate_head,
    )
    from yoke_core.domain.standalone_item_merge import StandaloneMergeOutcome
    from yoke_core.engines.merge_worktree_prepare import MergeArgs, MergeContext

    resolver = landed_candidate_head
    candidate = lane.candidate_sha or lane.commit_sha
    if (
        git.lane_adds_nothing(
            repo_root, candidate, git.current_base_ref(repo_root, lane.target)
        )
        is True
    ):
        from yoke_core.domain.merge_queue_landing_carrier import landing_carrier

        recorded = receipts.load(public_ref, lane.branch, lane.target, landed_only=True)
        newer_merge = bool(
            recorded is not None
            and recorded.merge_sha
            and lane.merge_sha
            and lane.merge_sha != recorded.merge_sha
            and git.is_ancestor(repo_root, recorded.merge_sha, lane.merge_sha)
        )
        if not newer_merge:
            try:
                if (
                    recorded is None
                    or not recorded.commit_sha
                    or not recorded.merge_sha
                ):
                    raise LandingUnverified(
                        "merge_recorded_landing_missing: no completed merge receipt for "
                        f"{public_ref}. Preserve the lane; restore the item's recorded "
                        "landing identity through the control-plane operator, then retry "
                        "the governed merge command."
                    )
                remote = verified_target_sha(repo_root, lane.target, recorded.merge_sha)
                verified_landing_identity(
                    repo_root, remote, recorded.commit_sha, recorded.merge_sha
                )
                if git.lane_adds_nothing(repo_root, candidate, remote) is not True:
                    raise LandingUnverified(
                        "merge_recorded_landing_content_unverified: the lane was not "
                        "proved unchanged against the fetched target. Preserve the lane; "
                        "refresh its target, verify any remaining work, and re-run the "
                        "governed merge command."
                    )
                carrier, reason = landing_carrier(
                    MergeContext(
                        args=MergeArgs(branch=lane.branch, target=lane.target),
                        repo_root=repo_root,
                        project=project,
                    ),
                    recorded.merge_sha,
                )
                if not carrier:
                    raise LandingUnverified(
                        f"merge_recorded_landing_carrier_unreadable: {reason}. "
                        "Preserve the lane; restore GitHub or merge-commit read access, "
                        "then retry the governed merge command."
                    )
            except LandingUnverified as exc:
                return StandaloneMergeOutcome(
                    ok=False, exit_code=1, already_merged=False, error=str(exc)
                )
            queue_pr_number = carrier
            candidate = recorded.commit_sha

            def resolver(_item):
                return recorded.commit_sha, ""

    closed = record_landing(
        MergeContext(
            args=MergeArgs(branch=lane.branch, target=lane.target),
            repo_root=repo_root,
            project=project,
        ),
        item_id=public_ref,
        commit_sha=lane.commit_sha,
        # A no-content lane uses the proved receipt identity. Other lanes
        # still require the observer to name their current candidate.
        candidate_sha=candidate,
        resolve_landed_head=resolver,
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
        commit_sha=closed.receipt_commit_sha or lane.commit_sha,
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
    pushed = False
    try:
        try:
            merge_sha = verified_target_sha(repo_root, lane.target, lane.commit_sha)
        except LandingUnverified:
            pushed, push_warning = git.publish(repo_root, lane.target)
            if push_warning:
                warnings.append(push_warning)
            merge_sha = verified_target_sha(repo_root, lane.target, lane.commit_sha)
        merge_sha = verified_landing_identity(
            repo_root,
            merge_sha,
            lane.commit_sha,
        )
    except LandingUnverified as exc:
        note = receipts.record_failure(
            item_id,
            branch=lane.branch,
            target=lane.target,
            label="merge_landing_unverified",
            phase="convergence",
            reason=str(exc),
        )
        if note:
            warnings.append(note)
        return StandaloneMergeOutcome(
            ok=False,
            exit_code=1,
            already_merged=False,
            commit_sha=lane.commit_sha,
            error=str(exc),
            pushed=pushed,
            warnings=tuple(warnings),
        )
    stamp_error = stamp_merged_at(
        item_id, repo_root=repo_root, merge_sha=lane.merge_sha or lane.commit_sha
    )
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
            contributed_commits=contributed.after_landing(
                repo_root,
                commit_sha=lane.commit_sha,
                merge_sha=merge_sha,
            ),
        ),
    )
    if receipt_note:
        warnings.append(receipt_note)

    if git.has_remote(repo_root):
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
