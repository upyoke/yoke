"""Whether a target branch already retains every change a branch carries.

Exact ancestry answers that for a branch that was merged. It answers "no"
for a branch that was rebased or squashed before it landed, even though the
target holds every change the branch carried — and that false negative is
what leaves a lane on disk after its item is terminal, because `git branch
-d` re-derives the same ancestry and refuses. Patch equivalence is the
second reading: when git pairs every commit the branch carries with an
equivalent commit already in the target, the branch holds nothing unique.

Every reading fails toward preserving. Unreadable history, a merge commit
patch equivalence cannot compare, or one commit with no equivalent in the
target keeps the branch with the reason named, because a preserved branch
costs an operator one sweep while a wrongly deleted one costs the work.

``run_git`` takes the git arguments after the executable and repository
selection, so each caller binds its own ``-C`` or ``cwd``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

ANCESTOR_PROOF = "ancestor"
PATCH_EQUIVALENT_PROOF = "patch_equivalent"


@dataclass(frozen=True)
class BranchLandedEvidence:
    """Verified git proof that a branch is, or is not, fully landed."""

    landed: bool
    proof: str = ""
    reason: str = ""


def _unique_commit_count(cherry_stdout: str) -> int:
    """How many commits git found no equivalent for in the target."""
    return sum(1 for line in cherry_stdout.splitlines() if line.startswith("+"))


def assess_branch_landed(
    run_git: Callable[[list[str]], Any], *, branch: str, base: str
) -> BranchLandedEvidence:
    """Prove whether ``base`` already retains every change on ``branch``."""
    ancestry = run_git(["merge-base", "--is-ancestor", branch, base])
    if ancestry.returncode == 0:
        return BranchLandedEvidence(True, proof=ANCESTOR_PROOF)

    not_merged = f"branch is not merged into {base}"
    merges = run_git(["rev-list", "--merges", f"{base}..{branch}"])
    if merges.returncode != 0:
        return BranchLandedEvidence(
            False, reason=f"{not_merged} and its history could not be read"
        )
    if (merges.stdout or "").strip():
        # git cherry compares patch ids and skips merges outright, so a
        # branch carrying one has no complete equivalence proof to offer.
        return BranchLandedEvidence(
            False,
            reason=f"{not_merged} and carries a merge commit equivalence cannot prove",
        )

    cherry = run_git(["cherry", base, branch])
    if cherry.returncode != 0:
        return BranchLandedEvidence(
            False, reason=f"{not_merged} and could not be compared against it"
        )
    unique = _unique_commit_count(cherry.stdout or "")
    if unique:
        plural = "s" if unique != 1 else ""
        return BranchLandedEvidence(
            False,
            reason=(
                f"{not_merged} and carries {unique} commit{plural} "
                f"with no equivalent there"
            ),
        )
    return BranchLandedEvidence(True, proof=PATCH_EQUIVALENT_PROOF)


def delete_landed_branch(
    run_git: Callable[[list[str]], Any],
    *,
    branch: str,
    evidence: BranchLandedEvidence,
) -> str:
    """Delete a branch this module proved landed; return why it survived.

    The delete is forced because the proof above is the stronger one: git's
    own ``-d`` safety re-derives exact ancestry and so refuses precisely the
    rebased branch whose changes the target already holds. Nothing calls
    this without the matching evidence — an unlanded branch is returned as
    preserved instead of deleted.
    """
    if not evidence.landed:
        return evidence.reason or f"local branch {branch} is not proven landed"
    deleted = run_git(["branch", "-D", branch])
    if deleted.returncode != 0:
        return f"local branch {branch} preserved after delete refusal"
    return ""


__all__ = [
    "ANCESTOR_PROOF",
    "PATCH_EQUIVALENT_PROOF",
    "BranchLandedEvidence",
    "assess_branch_landed",
    "delete_landed_branch",
]
