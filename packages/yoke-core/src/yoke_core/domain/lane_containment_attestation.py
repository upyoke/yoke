"""Answer containment where the checkout is, for a server that has none.

The containment question — does the deployed candidate already carry this
item's merge — is asked by the done gate on the control plane, which for an
https project holds no checkout of that project and must read the answer
through the repository provider. That reader is honest but weak: it cannot
merge trees, so a lane whose work reached the base under other commit ids,
or whose paths the base moved further on afterwards, is unknown to it.

At close-out the client is standing in the lane, with both commits and a
real git. It can answer the same question exactly, with the same two tests
the merge boundary already uses for everything else it decides
(:func:`standalone_item_merge_git.is_ancestor` and
:func:`standalone_item_merge_git.lane_adds_nothing`), so it answers once and
relays the verdict with its terminal transition.

What travels is the answer plus the facts that make it checkable: both
commits, and which test produced it. The server matches the pair against the
question it was actually asking before it uses the answer, so an attestation
about some other candidate can only be ignored, never mistaken for this one.
This is the trust boundary the client-written ``item_worktrees.commit_sha``
already sits on: the side holding the checkout is the side that can see.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain import standalone_item_merge_git as git


CONTAINED = "contained"
NOT_CONTAINED = "not_contained"

#: Which test answered, so the recorded evidence says how it was decided.
METHOD_ANCESTRY = "ancestry"
METHOD_ADDS_NOTHING = "lane_adds_nothing"


def lane_containment(
    repo_root: str,
    *,
    candidate: str,
    commit_sha: str,
) -> Optional[dict[str, Any]]:
    """Attest whether ``candidate`` already carries ``commit_sha``.

    ``None`` when this lane cannot answer — either commit missing from the
    checkout, or a merge the tree comparison could not run. An unanswered
    question relays nothing rather than relaying a guess, because the server
    has no way to tell a weak answer from a strong one once it arrives.
    """
    resolved_candidate = _resolve(repo_root, candidate)
    resolved_commit = _resolve(repo_root, commit_sha)
    if not resolved_candidate or not resolved_commit:
        return None
    facts = {
        # Both forms travel: the server asks about the candidate as its run
        # recorded it, which is a full sha for most releases and a ref for
        # the rest, and an attestation that matches neither is unusable.
        "candidate_ref": str(candidate).strip(),
        "candidate_sha": resolved_candidate,
        "commit_sha": resolved_commit,
    }
    if git.is_ancestor(repo_root, resolved_commit, resolved_candidate):
        return {**facts, **_verdict(CONTAINED, METHOD_ANCESTRY)}
    adds_nothing = git.lane_adds_nothing(repo_root, resolved_commit, resolved_candidate)
    if adds_nothing is None:
        return None
    return {
        **facts,
        **_verdict(
            CONTAINED if adds_nothing else NOT_CONTAINED, METHOD_ADDS_NOTHING
        ),
    }


def _resolve(repo_root: str, ref: str) -> str:
    """The full commit ``ref`` names in this checkout, or ``""``.

    Resolved before either test so a ref the lane never fetched answers
    "cannot tell" here instead of answering "not an ancestor" from git,
    which is the same shape and the opposite meaning.
    """
    token = str(ref or "").strip()
    if not token:
        return ""
    return git.git_out(repo_root, "rev-parse", "--verify", f"{token}^{{commit}}")


def _verdict(state: str, method: str) -> dict[str, Any]:
    return {"state": state, "method": method, "source": "lane_checkout"}


__all__ = [
    "CONTAINED",
    "METHOD_ADDS_NOTHING",
    "METHOD_ANCESTRY",
    "NOT_CONTAINED",
    "lane_containment",
]
