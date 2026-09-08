"""Whether a standalone lane's work is already on its base branch.

Every close-out step after the merge assumes there is still something to
land, and three of them are not free when that assumption is wrong. The
commit-bound QA recovery re-executes a SHA-bound CI case, which publishes the
lane — and publishing a lane whose pull request is sitting in the merge queue
is refused by GitHub and drops the pull request out of the train. Full queue
admission is wrong after landing too. A durable queue handoff marker is enough
to run only its post-landing bookkeeping: recover the identified merge-group
proof and receipt without publishing or re-entering the pull request.

So the merge boundary asks this question once, before any of them, and
converges when the answer is yes. Skipping the pre-merge QA gate on that path
waives nothing: the gate exists to refuse *before* a branch lands, and the
terminal ``done`` transition still runs the same blocking-run check against
the merge identity recorded here.

The answer comes from the checkout and the durable receipt, never from
GitHub. A landing is exactly "the base branch contains the lane", and ``git
fetch`` answers that while an API token or an SSH tunnel is still down —
which is the state the boundary is most often re-entered in.

Which commit the landing is *answerable for* is a second question with a
different answer. The lane head decides whether anything is left to merge;
the receipt names the commit the merge recorded, and that is the one evidence
must carry, because a lane fast-forwarded onto the base after its merge points
at the merge commit rather than at the work.

Close-out therefore compares the current lane candidate to those recorded
identities before it stamps, records, or cleans. Matching the recorded
candidate is the same landing even when a squash is not an ancestor of the
base. A different candidate that the base does not contain is new work: the
recovery is a fresh work item with its own merge identity, not this close-out.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from yoke_core.domain import standalone_item_merge_git as git
from yoke_core.domain import item_merge_receipts as receipts
from yoke_core.engines.main_checkout_sync import fast_forward_main_checkout


@dataclass(frozen=True)
class LandedLane:
    """One standalone lane whose work the base branch already contains."""

    branch: str
    target: str
    commit_sha: str
    merge_sha: str = ""
    touched_files: tuple[str, ...] = field(default=())
    source: str = ""


def _norm(sha: str) -> str:
    return sha.strip().lower()


def _recorded_identities(receipt: Optional[receipts.MergeReceipt]) -> set[str]:
    if receipt is None:
        return set()
    return {sha for sha in (_norm(receipt.commit_sha), _norm(receipt.merge_sha)) if sha}


def current_candidate(repo_root: str, branch: str, recorded_head: str = "") -> str:
    """The commit the live branch points at, else the last recorded lane head."""
    if git.branch_exists(repo_root, branch):
        return git.head_of(repo_root, branch).strip()
    return (recorded_head or "").strip()


def stale_unlanded_work(
    *,
    item_id: int,
    branch: str,
    target: str,
    repo_root: str,
    recorded_head: str = "",
) -> str:
    """Why this close-out must not run, or empty when the landing still matches.

    A recorded receipt is the landing identity. Matching it — including a
    squash whose original head is not on the base — is crash re-entry. A
    different head the base does not contain is new work and must not be
    declared delivered or cleaned here.
    """
    current = current_candidate(repo_root, branch, recorded_head)
    identities = _recorded_identities(receipts.load(item_id, branch, target))
    if not current or not identities:
        return ""
    if _norm(current) in identities:
        return ""
    if git.containing_ref(repo_root, current, target):
        return ""
    named = ", ".join(sorted(sha[:12] for sha in identities))
    return (
        f"branch {branch!r} head {current[:12]} is not the recorded landing "
        f"({named}); file a fresh work item so the new commits get their own "
        "merge identity. Close-out will not declare them delivered or clean "
        "this lane"
    )


def _describe(
    *,
    item_id: int,
    branch: str,
    target: str,
    repo_root: str,
    project: str,
    landed_sha: str,
    containing: str,
    source: str,
) -> LandedLane:
    """Name the commit, merge, and files this landing is answerable for."""
    recorded = receipts.load(item_id, branch, target)
    commit_sha = landed_sha
    if (
        recorded is not None
        and recorded.commit_sha
        and git.is_ancestor(repo_root, recorded.commit_sha, containing)
    ):
        commit_sha = recorded.commit_sha
    merge_sha = (recorded.merge_sha if recorded is not None else "") or (
        receipts.landing_merge_commit(repo_root, containing, commit_sha)
    )
    return LandedLane(
        branch=branch,
        target=target,
        commit_sha=commit_sha,
        merge_sha=merge_sha,
        touched_files=receipts.resolve_touched_files(
            repo_root=repo_root,
            target=containing,
            commit_sha=commit_sha,
            recorded=recorded,
            observed=(),
        ),
        source=source,
    )


def landed_lane(
    *,
    item_id: int,
    branch: str,
    target: str,
    repo_root: str,
    project: str,
    recorded_head: str = "",
) -> Optional[LandedLane]:
    """The landing this lane already has, or ``None`` when work is left.

    While the branch exists it is the authority on that question: a lane
    whose head is not a recorded landing identity and that the base does not
    contain has not landed. Matching a recorded identity is the same landing
    even when a squash is not an ancestor of the base. Once the branch is gone
    the recorded lane head answers, and the receipt after it.
    """
    receipt = receipts.load(item_id, branch, target)
    identities = _recorded_identities(receipt)
    if git.branch_exists(repo_root, branch):
        head = git.head_of(repo_root, branch)
        containing = git.containing_ref(repo_root, head, target)
        if not containing and _norm(head) not in identities:
            return None
        return _describe(
            item_id=item_id,
            branch=branch,
            target=target,
            repo_root=repo_root,
            project=project,
            landed_sha=head,
            containing=containing or target,
            source="lane branch" if containing else "merge receipt",
        )
    candidates = [(recorded_head, "recorded lane head")]
    if receipt is not None:
        candidates.append((receipt.commit_sha, "merge receipt"))
        candidates.append((receipt.merge_sha, "merge receipt"))
    for candidate, source in candidates:
        containing = git.containing_ref(repo_root, candidate, target)
        if containing:
            return _describe(
                item_id=item_id,
                branch=branch,
                target=target,
                repo_root=repo_root,
                project=project,
                landed_sha=candidate,
                containing=containing,
                source=source,
            )
    return None


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
    """Record what a lane that already landed still owes to its item.

    The merge itself is done, so this is bookkeeping the caller's evidence and
    terminal transition read afterwards: the ``merged_at`` stamp, a receipt
    naming the merge identity, and — when the landing never reached origin
    because the process carrying it died first — the push that publishes it.
    """
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


__all__ = [
    "LandedLane",
    "converge",
    "current_candidate",
    "landed_lane",
    "stale_unlanded_work",
]
