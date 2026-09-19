"""Why a close-out must not run against a lane that moved past its landing.

The landing question — is this lane's work already on the base — is
:mod:`yoke_core.domain.standalone_item_merge_landed`. This is the refusal
that sits beside it: a branch whose head is neither the recorded landing nor
anything the base contains is carrying work nobody landed, and a close-out
that proceeded there would declare undelivered work delivered and retire the
lane holding it.

Kept apart from the landing read because they answer opposite questions and
only this one composes a message an owner acts on — including which files
stop the lane converging, since a rebase and a bookkeeping drift look
identical from the shas alone.
"""

from __future__ import annotations

from yoke_core.domain import item_merge_receipts as receipts
from yoke_core.domain import standalone_item_merge_git as git
from yoke_core.domain.standalone_item_merge_landed import (
    current_candidate,
    norm,
    recorded_landing,
    replayed_base_ref,
)


def stale_unlanded_work(
    *,
    item_id: int,
    branch: str,
    target: str,
    repo_root: str,
    recorded_head: str = "",
    stale_mismatch_is_foreign: bool = True,
) -> str:
    """Why this close-out must not run, or empty when the landing still matches.

    A target-contained receipt merge SHA proves the landing. Its source commit
    can match squash re-entry; any other uncontained head is new work.

    ``stale_mismatch_is_foreign`` selects whether a mismatch is close-out's
    foreign/stale refusal. ``True`` is the safe default — including when no
    release stage is declared, when the definition could not be read, and
    when the item is already closed out — and every close-out caller that
    omits it keeps that existing refusal. A caller that has already
    confirmed THIS same item still owns a declared release wait (the item's
    own next merge, including while it waits at that stage) passes
    ``False`` so that mismatch is not read as someone else's foreign work
    on a reused branch name. It never changes what counts as a match; it
    only lets a genuine mismatch pass when the item's own state already
    accounts for it.
    """
    current = current_candidate(repo_root, branch, recorded_head)
    receipt = receipts.load(item_id, branch, target)
    identities, _ = recorded_landing(receipt, repo_root, target)
    if not current or not identities:
        return ""
    if norm(current) in identities:
        return ""
    if git.containing_ref(repo_root, current, target):
        return ""
    if replayed_base_ref(repo_root, current, target, receipt):
        return ""
    if not stale_mismatch_is_foreign:
        return ""
    named = ", ".join(sorted(sha[:12] for sha in identities))
    return (
        f"branch {branch!r} head {current[:12]} is past its recorded landing "
        f"({named})"
        f"{_conflict_clause(repo_root, current, target)}. Same-item "
        "correction continues through a declared "
        "release wait on the same item and lane; this refusal preserves "
        "the lane when the item is already closed out, or when the pinned "
        "workflow declares no release wait. Do not prescribe a stage "
        "change or reset unlanded corrections. Close-out will not declare "
        "them delivered or clean this lane"
    )


def _conflict_clause(repo_root: str, head: str, target: str) -> str:
    """Name the paths that stop this lane converging, when that is why.

    Without it the refusal says only that the head is not the landing,
    which reads as bookkeeping drift and invites a retry. The lane may
    instead carry a version of a file the base has since moved past, and
    that is a rebase, not a convergence — so say which files, because the
    owner cannot see it from the shas.
    """
    base = git.current_base_ref(repo_root, target)
    if not base:
        return ""
    paths = git.lane_merge_conflicts(repo_root, head, base)
    if not paths:
        return ""
    shown = ", ".join(paths[:5])
    more = f" (and {len(paths) - 5} more)" if len(paths) > 5 else ""
    return (
        f", and merging it into {base} conflicts in {shown}{more} — the base "
        "moved past this lane there, so it needs a rebase rather than a "
        "convergence"
    )


__all__ = ["stale_unlanded_work"]
