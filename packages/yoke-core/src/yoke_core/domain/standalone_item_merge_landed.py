"""Whether a standalone lane's work is already on its base branch.

Every close-out step after the merge assumes there is still something to
land, and three of them are not free when that assumption is wrong. The
commit-bound QA recovery re-executes a SHA-bound CI case, which publishes the
lane — and publishing a lane whose pull request is sitting in the merge queue
is refused by GitHub and drops the pull request out of the train. The queue
route asks GitHub to take a pull request it has already merged, reading a
train run that no longer exists. And the pull-request lookup calls a lane that
was fast-forwarded onto the base after its own merge "commits beyond the pull
request that merged it", sending close-out off to open a second pull request
for work that already landed.

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
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from yoke_core.domain import standalone_item_merge_git as git
from yoke_core.domain import standalone_item_merge_receipt as receipts
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
    recorded = receipts.load(item_id, branch, target, project=project)
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

    While the branch exists it is the only authority on that question: a lane
    carrying commits the base does not have has not landed, whatever an older
    receipt says about an earlier head. Once the branch is gone the recorded
    lane head answers, and the receipt after it — the last surviving record of
    what the lane carried.
    """
    if git.branch_exists(repo_root, branch):
        head = git.head_of(repo_root, branch)
        containing = git.containing_ref(repo_root, head, target)
        if not containing:
            return None
        return _describe(
            item_id=item_id, branch=branch, target=target,
            repo_root=repo_root, project=project, landed_sha=head,
            containing=containing, source="lane branch",
        )
    candidates = [(recorded_head, "recorded lane head")]
    receipt = receipts.load(item_id, branch, target, project=project)
    if receipt is not None:
        candidates.append((receipt.commit_sha, "merge receipt"))
        candidates.append((receipt.merge_sha, "merge receipt"))
    for candidate, source in candidates:
        containing = git.containing_ref(repo_root, candidate, target)
        if containing:
            return _describe(
                item_id=item_id, branch=branch, target=target,
                repo_root=repo_root, project=project, landed_sha=candidate,
                containing=containing, source=source,
            )
    return None


def converge(
    *,
    item_id: int,
    project: str,
    repo_root: str,
    lane: LandedLane,
):
    """Record what a lane that already landed still owes to its item.

    The merge itself is done, so this is bookkeeping the caller's evidence and
    terminal transition read afterwards: the ``merged_at`` stamp, a receipt
    naming the merge identity, and — when the landing never reached origin
    because the process carrying it died first — the push that publishes it.
    """
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
            branch=lane.branch, target=lane.target,
            commit_sha=lane.commit_sha, merge_sha=merge_sha,
            touched_files=lane.touched_files,
        ),
        project=project,
    )
    if receipt_note:
        warnings.append(receipt_note)

    pushed = False
    if git.has_remote(repo_root):
        git.fetch_target(repo_root, lane.target)
        if not git.is_ancestor(
            repo_root, lane.commit_sha, f"origin/{lane.target}"
        ):
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


__all__ = ["LandedLane", "converge", "landed_lane"]
