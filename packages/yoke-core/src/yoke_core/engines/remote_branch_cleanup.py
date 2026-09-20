"""Fail-closed deletion of merged remote branches."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Literal

from yoke_core.engines.branch_landed_evidence import assess_branch_landed


RemoteBranchDeleteStatus = Literal["absent", "deleted", "preserved"]

# A merge is visible to the process that made it before the remote advertises
# it to everyone else, so the first ancestry read can miss a merge that has
# already happened. One short pause and one re-read close that window; a branch
# that is still not contained after it is genuinely unmerged.
ANCESTRY_RECHECK_DELAY_SECONDS = 2.0


@dataclass(frozen=True)
class RemoteBranchDeleteResult:
    """Outcome of a remote-branch cleanup proof and delete attempt."""

    status: RemoteBranchDeleteStatus
    reason: str
    # True only when the proof succeeded and said the remote still holds work
    # the target lacks. Every other preserve means the proof itself did not
    # complete, so a later attempt may still delete the branch.
    unmerged: bool = False

    @property
    def cleanup_complete(self) -> bool:
        """Whether callers may discard retry metadata and local refs."""
        return self.status in {"absent", "deleted"}

    @property
    def retryable(self) -> bool:
        """Whether running this cleanup again could reach a different answer.

        An unmerged remote is settled: no number of retries turns work the
        target does not have into work it does. Landing the branch or
        discarding it is the only thing that moves it.
        """
        return not self.cleanup_complete and not self.unmerged


def _preserved(reason: str) -> RemoteBranchDeleteResult:
    return RemoteBranchDeleteResult("preserved", reason)


def _refreshed_target_tip(
    run_git: Callable[[list[str]], Any],
    *,
    target_ref: str,
    remote_target: str,
) -> str:
    """Fetch the target branch again and resolve its tip, or ``""``."""
    fetched = run_git(["fetch", "origin", f"+{target_ref}:{remote_target}"])
    if fetched.returncode != 0:
        return ""
    resolved = run_git(["rev-parse", "--verify", f"{remote_target}^{{commit}}"])
    if resolved.returncode != 0:
        return ""
    return (resolved.stdout or "").strip()


def delete_remote_branch_if_merged(
    *,
    run_git: Callable[[list[str]], Any],
    branch: str,
    target_branch: str,
    sleep: Callable[[float], None] = time.sleep,
) -> RemoteBranchDeleteResult:
    """Delete one exact remote branch after refreshed, leased proof.

    ``run_git`` receives arguments after the ``git`` executable and repository
    selection. The branch is deleted only when the exact advertised ref can be
    fetched and resolved to the same commit, that commit is retained by a
    freshly fetched target branch, and the remote still advertises the expected
    commit when the leased delete executes.

    "Retained" is the shared landing proof: exact ancestry, or the patch
    equivalence a rebased or squashed lane leaves behind, so a remote branch
    whose changes the target already holds retires with its local lane
    instead of outliving it.

    A miss is re-read once after a short pause before it is believed,
    because a merge pushed moments earlier is not yet advertised to this
    checkout and losing that race preserves a lane that is already landed.
    """
    if branch == target_branch:
        return _preserved("cleanup branch is the target branch")

    for candidate, label in (
        (branch, "cleanup branch"),
        (target_branch, "target branch"),
    ):
        validated = run_git(["check-ref-format", "--branch", candidate])
        if validated.returncode != 0:
            return _preserved(f"{label} is not a valid branch name")

    exact_ref = f"refs/heads/{branch}"
    target_ref = f"refs/heads/{target_branch}"
    listed = run_git(["ls-remote", "--heads", "origin", exact_ref])
    if listed.returncode != 0:
        return _preserved("remote branch could not be inspected")

    advertised: list[tuple[str, str]] = []
    for line in (listed.stdout or "").splitlines():
        fields = line.split()
        if len(fields) != 2 or fields[1] != exact_ref:
            return _preserved("remote branch advertisement was ambiguous")
        advertised.append((fields[0], fields[1]))
    if not advertised:
        return RemoteBranchDeleteResult("absent", "remote branch is absent")
    if len(advertised) != 1:
        return _preserved("remote branch advertisement was ambiguous")
    advertised_sha = advertised[0][0]

    remote_target = f"refs/remotes/origin/{target_branch}"
    target_fetch = run_git(
        ["fetch", "origin", f"+{target_ref}:{remote_target}"]
    )
    if target_fetch.returncode != 0:
        return _preserved("target branch could not be refreshed")

    remote_branch = f"refs/remotes/origin/{branch}"
    branch_fetch = run_git(
        ["fetch", "origin", f"+{exact_ref}:{remote_branch}"]
    )
    if branch_fetch.returncode != 0:
        return _preserved("remote branch could not be refreshed")

    branch_tip = run_git(
        ["rev-parse", "--verify", f"{remote_branch}^{{commit}}"]
    )
    resolved_sha = (branch_tip.stdout or "").strip()
    if branch_tip.returncode != 0 or resolved_sha != advertised_sha:
        return _preserved("remote branch changed while cleanup was proving it")

    target_tip = run_git(
        ["rev-parse", "--verify", f"{remote_target}^{{commit}}"]
    )
    target_sha = (target_tip.stdout or "").strip()
    if target_tip.returncode != 0 or not target_sha:
        return _preserved("refreshed target branch could not be resolved")

    landed = assess_branch_landed(run_git, branch=resolved_sha, base=target_sha)
    if not landed.landed:
        sleep(ANCESTRY_RECHECK_DELAY_SECONDS)
        target_sha = _refreshed_target_tip(
            run_git, target_ref=target_ref, remote_target=remote_target
        )
        if not target_sha:
            return _preserved("refreshed target branch could not be resolved")
        landed = assess_branch_landed(run_git, branch=resolved_sha, base=target_sha)
    if not landed.landed:
        return RemoteBranchDeleteResult(
            "preserved", f"remote branch {landed.reason}", unmerged=True
        )

    deleted = run_git(
        [
            "push",
            f"--force-with-lease={exact_ref}:{resolved_sha}",
            "origin",
            f":{exact_ref}",
        ]
    )
    if deleted.returncode != 0:
        return _preserved("leased remote delete was refused")
    return RemoteBranchDeleteResult("deleted", "remote branch was deleted")


def unmerged_remote_note(branch: str, reason: str) -> str:
    """Name a remote branch that outlived the local lane it belonged to.

    Both retirement boundaries emit this, so they describe the same leftover
    the same way. The worktree and local branch are already gone by the time
    anyone reads it, so it has to carry what is left and how to finish it.
    """
    return (
        f"remote branch origin/{branch} kept after its local lane retired: "
        f"{reason}. No sweep revisits it — land origin/{branch} or delete it."
    )


__all__ = [
    "RemoteBranchDeleteResult",
    "delete_remote_branch_if_merged",
    "unmerged_remote_note",
]
