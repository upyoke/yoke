"""Whether a standalone lane's work is already on its base branch.

Every close-out step after the merge assumes there is still something to
land, and three of them are not free when that assumption is wrong. The
commit-bound QA recovery re-executes a SHA-bound CI case, which publishes the
lane — and publishing a lane whose pull request is sitting in the merge queue
is refused by GitHub and drops the pull request out of the train. A durable
queue handoff instead runs only post-landing bookkeeping.

The boundary asks once and converges when the answer is yes. This waives no QA:
the gate refuses *before* landing, and ``done`` rechecks the merge identity.

The answer comes from Git: the target must contain the lane head or a
receipt's merge SHA. A receipt's source commit alone is never landing proof.

Which commit the landing is *answerable for* is a second question with a
different answer. The lane head decides whether anything is left to merge;
the receipt names the commit the merge recorded, and that is the one evidence
must carry, because a lane fast-forwarded onto the base after its merge points
at the merge commit rather than at the work.

Close-out therefore compares the current lane candidate to those recorded
identities before it stamps, records, or cleans. Matching the recorded
candidate is the same landing even when a squash is not an ancestor of the
base. A different candidate that the base does not contain is new work.
Same-item correction continues on the same item and lane through a
declared release wait: re-verify, review, and run the governed merge
again, then a fresh selected-flow delivery. Do not prescribe a stage
change. The mismatch refusal preserves the lane when the item is
already closed out, or when the pinned workflow declares no release
wait. Do not reset unlanded corrections.

Rebasing after a landing is neither of those, and it is the case sha reads
cannot see: the base holds the work, the lane holds new shas for the same
patches, and calling that new work sends close-out off to publish the lane
and open a second pull request for a merge that already happened. The same
is true of extra lane commits that reached the base under a *different*
item's landing. So a head the base does not contain is asked one further
question — by content rather than by sha, and only once a recorded merge is
confirmed on the base — see :func:`_replayed_base_ref`.

What a landed lane then owes its item is a separate concern, owned by
:mod:`yoke_core.domain.standalone_item_merge_converge`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from yoke_core.domain import standalone_item_merge_git as git
from yoke_core.domain import item_merge_receipts as receipts


@dataclass(frozen=True)
class LandedLane:
    """One standalone lane whose work the base branch already contains."""

    branch: str
    target: str
    commit_sha: str
    merge_sha: str = ""
    touched_files: tuple[str, ...] = field(default=())
    source: str = ""
    # The commit THIS close-out is converging, before the receipt
    # substitution replaces it for evidence purposes. Anything resolving a
    # merge for the work in hand -- the landing carrier the marker is
    # repointed at -- reads this rather than ``commit_sha``.
    candidate_sha: str = ""


def norm(sha: str) -> str:
    return sha.strip().lower()


def recorded_landing(
    receipt: Optional[receipts.MergeReceipt],
    repo_root: str,
    target: str,
) -> tuple[set[str], str]:
    if receipt is None or not receipt.merge_sha:
        return set(), ""
    merge_sha = norm(receipt.merge_sha)
    containing = git.containing_ref(repo_root, merge_sha, target)
    if not containing:
        return set(), ""
    return {sha for sha in (norm(receipt.commit_sha), merge_sha) if sha}, containing


def current_candidate(repo_root: str, branch: str, recorded_head: str = "") -> str:
    """The commit the live branch points at, else the last recorded lane head."""
    if git.branch_exists(repo_root, branch):
        return git.head_of(repo_root, branch).strip()
    return (recorded_head or "").strip()


def replayed_base_ref(
    repo_root: str,
    head: str,
    target: str,
    receipt: Optional[receipts.MergeReceipt],
) -> str:
    """The base ref already holding this lane's work under different shas.

    A recorded landing is always required first: the base must contain the
    commit the merge receipt recorded, which is the landing whose identity a
    convergence here preserves. Patch or tree equivalence alone is never a
    landing — without a recorded merge on the base there is no identity to
    converge on, whatever the content says.

    Given that landing, two reads answer whether the lane still carries
    anything beyond it, and either suffices. The direct one asks whether
    merging the lane into the base would change the base at all; a lane that
    adds nothing has nothing left to land, whatever shape its commits take,
    which is what recognises extra lane commits that reached the base under a
    companion item's landing — foreign shas, and possibly merges patch
    identity will not speak for. The second is the older patch-identity read,
    kept because it answers where a tree merge cannot run.

    A lane still carrying content of its own answers empty under both, which
    is what keeps a retry after a red train and deliberate new work on the
    ordinary landing route. So does a comparison that could not run, because
    reading an unreadable checkout as "already landed" is the one mistake
    that closes an item out against a merge nobody confirmed.
    """
    recorded = receipt.commit_sha if receipt is not None else ""
    if not recorded or not head:
        return ""
    base = git.current_base_ref(repo_root, target)
    if not git.is_ancestor(repo_root, recorded, base):
        return ""
    # Content first: would merging this lane into the base change the base at
    # all? A lane whose extra commits reached the base under a companion
    # item's landing answers no, and neither sha nor patch identity can see
    # that — those shas are foreign to the base, and the lane may hold merges
    # patch identity will not speak for.
    if git.lane_adds_nothing(repo_root, head, base) is True:
        return base
    return base if git.unlanded_commits(repo_root, head, base) == () else ""


def base_holds(
    repo_root: str, candidate: str, target: str, receipt: Optional[receipts.MergeReceipt]
) -> bool:
    """Whether the base already carries ``candidate``, by sha or by content."""
    if git.containing_ref(repo_root, candidate, target):
        return True
    return bool(replayed_base_ref(repo_root, candidate, target, receipt))


def _recorded_describes(
    repo_root: str,
    containing: str,
    recorded: Optional[receipts.MergeReceipt],
    candidate_merge: str,
) -> bool:
    """Whether the recorded receipt speaks for the landing in hand.

    The receipt is preferred because a lane fast-forwarded onto the base
    points at the merge commit rather than at the work, and a rebased copy
    holds shas the base never saw; in both the candidate names no landing
    merge of its own and the receipt is the only identity there is.

    A lane that landed twice is what that preference gets wrong: the
    superseded candidate is equally on the base under a merge of its own,
    so the receipt describes a landing this close-out already replaced.
    A candidate that names a merge therefore keeps the receipt only when
    the receipt landed under that same merge.
    """
    if recorded is None or not recorded.commit_sha:
        return False
    if not git.is_ancestor(repo_root, recorded.commit_sha, containing):
        return False
    if not candidate_merge:
        return True
    return (
        receipts.landing_merge_commit(repo_root, containing, recorded.commit_sha)
        == candidate_merge
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
    """Name the commit, merge, and files this landing is answerable for.

    ``landed_sha`` is the candidate in hand and rides out untouched as
    ``candidate_sha``; everything else describes the landing that carried
    it, which is the recorded receipt only while that receipt speaks for
    the same landing.
    """
    recorded = receipts.load(item_id, branch, target)
    candidate_merge = receipts.landing_merge_commit(
        repo_root, containing, landed_sha
    )
    if not _recorded_describes(repo_root, containing, recorded, candidate_merge):
        recorded = None
    commit_sha = landed_sha
    if recorded is not None and recorded.commit_sha:
        commit_sha = recorded.commit_sha
    recorded_merge_sha = recorded.merge_sha if recorded is not None else ""
    if recorded_merge_sha and not git.is_ancestor(
        repo_root,
        recorded_merge_sha,
        containing,
    ):
        recorded_merge_sha = ""
    merge_sha = recorded_merge_sha or candidate_merge
    return LandedLane(
        branch=branch,
        target=target,
        commit_sha=commit_sha,
        candidate_sha=landed_sha,
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

    The live branch is authoritative unless a target-contained receipt proves
    its matching squash landing, or the base branch already carries every
    patch the branch holds. Once the branch is gone, the recorded lane head
    answers in its place under the same rule — and answers alone: only when
    no candidate was ever recorded does the receipt's own shas decide, and
    that is a lane with nothing else to be asked about.

    A recorded candidate the base does not contain, by sha or by content,
    means this lane still has work to land whatever an earlier landing on
    the same branch name recorded.
    """
    receipt = receipts.load(item_id, branch, target)
    identities, receipt_ref = recorded_landing(receipt, repo_root, target)
    recorded = str(recorded_head or "").strip()
    if recorded and not base_holds(repo_root, recorded, target, receipt):
        # The control plane's own candidate -- what the gate verified and
        # what was published -- is not on the base by sha or by content, so
        # this lane still has something to land. Asked before the local
        # branch, because a branch NAME outlives the landing it had: a stale
        # local ref sitting on an earlier merge of the same name otherwise
        # matched the recorded identities and converged the new candidate
        # onto an older merge that never carried it.
        return None
    if git.branch_exists(repo_root, branch):
        head = git.head_of(repo_root, branch)
        containing = git.containing_ref(repo_root, head, target)
        replayed = (
            "" if containing else replayed_base_ref(repo_root, head, target, receipt)
        )
        if not containing and not replayed and norm(head) not in identities:
            return None
        return _describe(
            item_id=item_id,
            branch=branch,
            target=target,
            repo_root=repo_root,
            project=project,
            landed_sha=head,
            containing=containing or replayed or receipt_ref,
            source=(
                "lane branch"
                if containing
                else "rebased copy of the landed lane"
                if replayed
                else "merge receipt"
            ),
        )
    head = str(recorded_head or "").strip()
    if head:
        # The recorded candidate answers on its own, exactly as the live
        # branch does. Falling past it to the receipt's older shas is what
        # let a branch name that had landed before report a NEW candidate as
        # already merged: the item then carried an evidence record naming a
        # merge that predates the work it describes, and advanced on a
        # candidate nothing had landed.
        containing = git.containing_ref(repo_root, head, target)
        replayed = (
            "" if containing else replayed_base_ref(repo_root, head, target, receipt)
        )
        if not containing and not replayed:
            return None
        return _describe(
            item_id=item_id,
            branch=branch,
            target=target,
            repo_root=repo_root,
            project=project,
            landed_sha=head,
            containing=containing or replayed,
            source=(
                "recorded lane head"
                if containing
                else "rebased copy of the landed lane"
            ),
        )
    if receipt is None:
        return None
    for candidate, source in (
        (receipt.commit_sha, "merge receipt"),
        (receipt.merge_sha, "merge receipt"),
    ):
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


__all__ = [
    "LandedLane",
    "base_holds",
    "norm",
    "current_candidate",
    "landed_lane",
    "recorded_landing",
    "replayed_base_ref",
]
