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
base. A different candidate that the base does not contain is new work: the
recovery is a fresh work item with its own merge identity, not this close-out.

Rebasing after a landing is neither of those, and it is the case sha reads
cannot see: the base holds the work, the lane holds new shas for the same
patches, and calling that new work sends close-out off to publish the lane
and open a second pull request for a merge that already happened. So a head
the base does not contain is asked one further question, by patch identity
rather than by sha — see :func:`_replayed_base_ref`.

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


def _norm(sha: str) -> str:
    return sha.strip().lower()


def _recorded_landing(
    receipt: Optional[receipts.MergeReceipt],
    repo_root: str,
    target: str,
) -> tuple[set[str], str]:
    if receipt is None or not receipt.merge_sha:
        return set(), ""
    merge_sha = _norm(receipt.merge_sha)
    containing = git.containing_ref(repo_root, merge_sha, target)
    if not containing:
        return set(), ""
    return {sha for sha in (_norm(receipt.commit_sha), merge_sha) if sha}, containing


def current_candidate(repo_root: str, branch: str, recorded_head: str = "") -> str:
    """The commit the live branch points at, else the last recorded lane head."""
    if git.branch_exists(repo_root, branch):
        return git.head_of(repo_root, branch).strip()
    return (recorded_head or "").strip()


def _replayed_base_ref(
    repo_root: str,
    head: str,
    target: str,
    receipt: Optional[receipts.MergeReceipt],
) -> str:
    """The base ref already holding this lane's work under different shas.

    Rebasing a lane rewrites every commit it carries, so a lane rebased after
    its own landing points at copies no ancestry read can attribute to the
    merge that took them. Two facts together make them copies rather than new
    work, and both are required: the base contains the commit the merge
    receipt recorded — the landing whose identity a convergence here
    preserves — and the lane holds no commit whose patch that base lacks.

    A lane carrying a commit of its own answers empty, which is what keeps a
    retry after a red train and deliberate new work on the ordinary landing
    route — as does a lane holding a merge the base lacks, whose content
    patch identity cannot speak for. So does a comparison that could not run,
    because reading an unreadable checkout as "already landed" is the one
    mistake that closes an item out against a merge nobody confirmed.
    """
    recorded = receipt.commit_sha if receipt is not None else ""
    if not recorded or not head:
        return ""
    base = git.current_base_ref(repo_root, target)
    if not git.is_ancestor(repo_root, recorded, base):
        return ""
    return base if git.unlanded_commits(repo_root, head, base) == () else ""


def stale_unlanded_work(
    *,
    item_id: int,
    branch: str,
    target: str,
    repo_root: str,
    recorded_head: str = "",
) -> str:
    """Why this close-out must not run, or empty when the landing still matches.

    A target-contained receipt merge SHA proves the landing. Its source commit
    can match squash re-entry; any other uncontained head is new work.
    """
    current = current_candidate(repo_root, branch, recorded_head)
    receipt = receipts.load(item_id, branch, target)
    identities, _ = _recorded_landing(receipt, repo_root, target)
    if not current or not identities:
        return ""
    if _norm(current) in identities:
        return ""
    if git.containing_ref(repo_root, current, target):
        return ""
    if _replayed_base_ref(repo_root, current, target, receipt):
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
    recorded_merge_sha = recorded.merge_sha if recorded is not None else ""
    if recorded_merge_sha and not git.is_ancestor(
        repo_root,
        recorded_merge_sha,
        containing,
    ):
        recorded_merge_sha = ""
    merge_sha = recorded_merge_sha or (
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

    The live branch is authoritative unless a target-contained receipt proves
    its matching squash landing, or the base branch already carries every
    patch the branch holds. Once the branch is gone, the recorded head and
    receipt answer from the same target-containment proof.
    """
    receipt = receipts.load(item_id, branch, target)
    identities, receipt_ref = _recorded_landing(receipt, repo_root, target)
    if git.branch_exists(repo_root, branch):
        head = git.head_of(repo_root, branch)
        containing = git.containing_ref(repo_root, head, target)
        replayed = (
            "" if containing else _replayed_base_ref(repo_root, head, target, receipt)
        )
        if not containing and not replayed and _norm(head) not in identities:
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


__all__ = [
    "LandedLane",
    "current_candidate",
    "landed_lane",
    "stale_unlanded_work",
]
