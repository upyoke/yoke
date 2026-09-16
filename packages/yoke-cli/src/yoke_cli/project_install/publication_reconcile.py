"""Read the publish branch's remote, and reconcile it by regeneration.

The installer generates a managed layer and commits it onto the checkout's
default branch. Between that commit and its push the remote can advance, and
this module resolves that: move the local branch onto the remote tip, then
let the caller REGENERATE the managed layer on that new base.

Regeneration — not a merge preference — is what makes the result correct. A
``merge -X theirs`` keeps whatever non-conflicting content the older side
added, so a block this Yoke version no longer renders survives the merge and
the operator cleans it by hand afterwards. Re-running the bundle write on the
updated base produces exactly the content this version renders, and the
managed-block mechanics preserve the operator's own text around it.

Bringing a branch current BEFORE work starts is the shared project freshness
contract (:mod:`yoke_cli.config.repo_upstream_freshness`), which the install
calls once; this module is publication-time only. The git mechanics it needs
— naming the tracking remote, fetching, and comparing — come from that
contract's :mod:`yoke_cli.config.repo_upstream_git` sibling rather than a
second implementation of reaching a remote.

Nothing here force-pushes and nothing here rewrites work the operator has not
published. Commits the remote lacks are replaced only when every one of them
is an installer commit; anything else is reported as divergence with its
recovery. The branch move itself goes through ``git switch``, which refuses
rather than overwrite unexpected local modifications.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from yoke_cli.config import repo_upstream_git as upstream_git
from yoke_cli.project_install import checkout_gate
from yoke_cli.project_install.files import ProjectInstallError


NOT_A_GIT_CHECKOUT = "not_a_git_checkout"
NO_REMOTE = "no_remote"
REMOTE_UNRESOLVED = "remote_unresolved"
REMOTE_BRANCH_MISSING = "remote_branch_missing"
FETCH_FAILED = "fetch_failed"
CURRENT = "current"
BEHIND = "behind"
AHEAD = "ahead"
DIVERGED = "diverged"

_MISSING_REF_SIGNATURES = ("couldn't find remote ref", "unknown revision")


@dataclass(frozen=True)
class RemoteState:
    """What the remote holds for the publish branch, and how local relates."""

    status: str
    remote: str = ""
    branch: str = ""
    local_sha: str = ""
    remote_sha: str = ""
    detail: str = ""
    local_only: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    @property
    def operator_commits(self) -> tuple[str, ...]:
        """Local-only commits this installer did not author, newest first."""
        return tuple(
            f"{sha[:12]} {subject}"
            for sha, subject in self.local_only
            if not checkout_gate.is_installer_commit_message(subject)
        )

    def payload(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "remote": self.remote,
            "branch": self.branch,
            "local_sha": self.local_sha,
            "remote_sha": self.remote_sha,
            "local_only_commits": [
                f"{sha[:12]} {subject}" for sha, subject in self.local_only
            ],
            **({"detail": self.detail} if self.detail else {}),
        }


def network_git(
    repo_root: Path, *args: str,
) -> subprocess.CompletedProcess:
    """Run a git command that reaches the remote, with the stored credential.

    One place an engine contacts a remote, shared with the upstream freshness
    reads: the stored credential reaches the fetch and the push alike, a
    missing one comes back as a failed result naming what restores it rather
    than a prompt no install has a terminal to answer, and the bound is the
    registered machine setting rather than a copy of it here.
    """
    return upstream_git.git(
        str(repo_root), *args, timeout=upstream_git.network_timeout_seconds(),
    )


def publish_remote(repo_root: Path, branch: str) -> str | None:
    """Return the remote this branch publishes to, or None when local-only.

    The shared resolver reads git's own records — the branch's tracking
    remote, the push default, then a sole configured remote — and returns
    empty rather than guessing among several. Publication keeps that
    strictness: pushing the layer to a remote nobody nominated is worse than
    saying which record is missing.
    """
    name, _configured = upstream_git.resolve_remote(str(repo_root), branch)
    return name or None


def read_remote_state(
    repo_root: Path, *, branch: str, remote: str | None = None,
) -> RemoteState:
    """Fetch the branch's remote ref and classify local against it."""
    if not checkout_gate.is_git_checkout(repo_root):
        return RemoteState(NOT_A_GIT_CHECKOUT)
    resolved = remote
    configured = 0
    if not resolved:
        resolved, configured = upstream_git.resolve_remote(str(repo_root), branch)
    if not resolved:
        return RemoteState(
            NO_REMOTE if configured == 0 else REMOTE_UNRESOLVED,
            branch=branch,
            detail=(
                ""
                if configured == 0
                else (
                    f"none of the {configured} configured remotes is recorded "
                    f"as tracking {branch}, so there is no remote to publish "
                    f"to. recipe: `git branch --set-upstream-to=<remote>/"
                    f"{branch} {branch}`"
                )
            ),
        )
    fetched = upstream_git.fetch_branch(str(repo_root), resolved, branch)
    local_sha = _rev_parse(repo_root, branch)
    if fetched.returncode != 0:
        detail = upstream_git.reason(fetched)
        lowered = detail.lower()
        missing = any(
            signature in lowered for signature in _MISSING_REF_SIGNATURES
        )
        return RemoteState(
            REMOTE_BRANCH_MISSING if missing else FETCH_FAILED,
            remote=resolved,
            branch=branch,
            local_sha=local_sha,
            detail=detail,
        )
    tracking = upstream_git.tracking_ref(resolved, branch)
    remote_sha = _rev_parse(repo_root, tracking)
    read, ahead, behind, compare_detail = upstream_git.count_ahead_behind(
        str(repo_root), local_sha, tracking,
    )
    if not remote_sha or not local_sha or not read:
        return RemoteState(
            FETCH_FAILED,
            remote=resolved,
            branch=branch,
            local_sha=local_sha,
            remote_sha=remote_sha,
            detail=(
                compare_detail
                or "the fetched remote tip or the local branch tip is unreadable"
            ),
        )
    if ahead and behind:
        status = DIVERGED
    elif ahead:
        status = AHEAD
    elif behind:
        status = BEHIND
    else:
        status = CURRENT
    return RemoteState(
        status,
        remote=resolved,
        branch=branch,
        local_sha=local_sha,
        remote_sha=remote_sha,
        local_only=_local_only_commits(repo_root, remote_sha, local_sha),
    )


def move_branch_onto(repo_root: Path, *, branch: str, sha: str) -> None:
    """Point ``branch`` and the working tree at ``sha`` without discarding work.

    ``git switch`` refuses rather than overwrite local modifications, so a
    checkout that is not as clean as the caller proved it to be stops here
    with git's own message instead of losing content.
    """
    dirty = checkout_gate.porcelain(repo_root)
    if dirty:
        listed = "\n".join(f"  {line}" for line in dirty)
        raise ProjectInstallError(
            "the checkout became dirty before the publish branch could be "
            f"moved onto {sha[:12]}, so nothing was moved:\n{listed}\n"
            "recipe: `git add -A && git commit` (or `git stash "
            "--include-untracked`), then re-run the install"
        )
    for args in (
        ("switch", "--detach", sha),
        ("branch", "--force", branch, sha),
        ("switch", branch),
    ):
        moved = checkout_gate.run_git(repo_root, *args)
        if moved.returncode != 0:
            detail = moved.stderr.strip() or moved.stdout.strip()
            raise ProjectInstallError(
                f"could not move {branch} onto {sha[:12]}: {detail}. "
                f"recipe: `git switch {branch}` in that checkout, resolve the "
                "reported state, then re-run the install"
            )


def reconcile_by_regeneration(
    repo_root: Path,
    *,
    branch: str,
    remote: str | None,
    regenerate: Callable[[], dict[str, Any]],
    operation: str,
) -> dict[str, Any]:
    """Move onto the advanced remote tip, regenerate, and re-commit.

    Returns the outcome plus the fresh commit result. ``regenerate`` re-runs
    the bundle write on the updated base; its report is what the replacement
    commit claims as its owned paths.
    """
    state = read_remote_state(repo_root, branch=branch, remote=remote)
    if state.status in (CURRENT, BEHIND):
        return {**state.payload(), "status": "already_published"}
    if state.status in (NOT_A_GIT_CHECKOUT, NO_REMOTE, REMOTE_BRANCH_MISSING):
        return {**state.payload(), "status": "not_reconcilable"}
    if state.status == FETCH_FAILED:
        return state.payload()
    if state.status == AHEAD:
        return {**state.payload(), "status": "remote_did_not_advance"}
    operator = state.operator_commits
    if operator:
        listed = "\n".join(f"  {line}" for line in operator)
        return {
            **state.payload(),
            "status": "operator_commits_present",
            "operator_commits": list(operator),
            "recovery": (
                f"{branch} carries commits {state.remote}/{branch} does not, "
                f"so the installed layer was not rebased onto it:\n{listed}\n"
                f"recipe: publish or rebase those commits yourself "
                f"(`git pull --rebase {state.remote} {branch}` then "
                f"`git push {state.remote} {branch}`), then re-run the "
                "install to publish the layer"
            ),
        }
    move_branch_onto(repo_root, branch=branch, sha=state.remote_sha)
    report = regenerate()
    commit = checkout_gate.commit_touched_paths(
        repo_root, report, operation=operation,
    )
    return {
        **state.payload(),
        "status": "regenerated",
        "regenerated_report": report,
        "commit": commit,
    }


def _rev_parse(repo_root: Path, revision: str) -> str:
    result = checkout_gate.run_git(repo_root, "rev-parse", "--verify", revision)
    return result.stdout.strip() if result.returncode == 0 else ""


def _local_only_commits(
    repo_root: Path, remote_sha: str, local_sha: str,
) -> tuple[tuple[str, str], ...]:
    listed = checkout_gate.run_git(
        repo_root, "log", "--format=%H%x00%s", f"{remote_sha}..{local_sha}",
    )
    if listed.returncode != 0:
        return ()
    commits: list[tuple[str, str]] = []
    for line in listed.stdout.splitlines():
        sha, _, subject = line.partition("\0")
        if sha.strip():
            commits.append((sha.strip(), subject.strip()))
    return tuple(commits)


__all__ = [
    "AHEAD",
    "BEHIND",
    "CURRENT",
    "DIVERGED",
    "FETCH_FAILED",
    "NO_REMOTE",
    "REMOTE_UNRESOLVED",
    "NOT_A_GIT_CHECKOUT",
    "REMOTE_BRANCH_MISSING",
    "RemoteState",
    "move_branch_onto",
    "network_git",
    "publish_remote",
    "read_remote_state",
    "reconcile_by_regeneration",
]
