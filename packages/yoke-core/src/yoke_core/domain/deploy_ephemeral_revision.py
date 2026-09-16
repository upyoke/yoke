"""Which commit a preview deploys, and proof that it exists.

Two previews answer this differently on purpose. A development preview
tracks a branch, so it takes whatever that branch points at right now and
moves when the branch moves — which is the feature. A release preview is
named for a run and pinned to that run's candidate, so it takes the exact
commit and must keep serving it while the branch advances underneath.

Both answers are verified against the checkout before anything deploys: a
revision this checkout cannot resolve would otherwise be built from
whatever that name happened to mean here, under an identity claiming it
was the candidate.
"""

from __future__ import annotations

from yoke_core.domain.deploy_ephemeral_files import EphemeralDeployError
from yoke_core.domain.deploy_remote import CommandRunner


def resolve_branch_sha(runner: CommandRunner, repo_path: str, branch: str) -> str:
    """The branch's local commit SHA — the worktree tier deploys local code."""
    if not repo_path:
        raise EphemeralDeployError(
            "[ephemeral] no project repo path available to resolve the branch SHA"
        )
    result = runner.run(["git", "-C", repo_path, "rev-parse", branch], timeout=30)
    if not result.ok or not result.stdout.strip():
        raise EphemeralDeployError(
            f"[ephemeral] could not resolve branch '{branch}' in "
            f"{repo_path}: {result.stderr.strip()}"
        )
    return result.stdout.strip()


def verify_revision(runner: CommandRunner, repo_path: str, revision: str) -> str:
    """The full commit for *revision*, refusing one this checkout lacks."""
    if not repo_path:
        raise EphemeralDeployError(
            "[ephemeral] no project repo path available to verify the "
            f"pinned revision '{revision}'"
        )
    result = runner.run(
        ["git", "-C", repo_path, "rev-parse", "--verify", f"{revision}^{{commit}}"],
        timeout=30,
    )
    if not result.ok or not result.stdout.strip():
        raise EphemeralDeployError(
            f"[ephemeral] pinned revision '{revision}' is not a commit in "
            f"{repo_path}: {result.stderr.strip()}"
        )
    return result.stdout.strip()


__all__ = ["resolve_branch_sha", "verify_revision"]
