"""Fail-closed deletion of merged remote branches."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal


RemoteBranchDeleteStatus = Literal["absent", "deleted", "preserved"]


@dataclass(frozen=True)
class RemoteBranchDeleteResult:
    """Outcome of a remote-branch cleanup proof and delete attempt."""

    status: RemoteBranchDeleteStatus
    reason: str

    @property
    def cleanup_complete(self) -> bool:
        """Whether callers may discard retry metadata and local refs."""
        return self.status in {"absent", "deleted"}


def _preserved(reason: str) -> RemoteBranchDeleteResult:
    return RemoteBranchDeleteResult("preserved", reason)


def delete_remote_branch_if_merged(
    *,
    run_git: Callable[[list[str]], Any],
    branch: str,
    target_branch: str,
) -> RemoteBranchDeleteResult:
    """Delete one exact remote branch after refreshed, leased proof.

    ``run_git`` receives arguments after the ``git`` executable and repository
    selection. The branch is deleted only when the exact advertised ref can be
    fetched and resolved to the same commit, that commit is retained by a
    freshly fetched target branch, and the remote still advertises the expected
    commit when the leased delete executes.
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

    ancestry = run_git(
        ["merge-base", "--is-ancestor", resolved_sha, target_sha]
    )
    if ancestry.returncode != 0:
        return _preserved("remote branch is not merged into the target branch")

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


__all__ = [
    "RemoteBranchDeleteResult",
    "delete_remote_branch_if_merged",
]
