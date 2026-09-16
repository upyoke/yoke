"""Read the publish branch's remote, and reconcile it by regeneration.

The installer generates a managed layer and commits it onto the checkout's
default branch. That branch can be older than the remote either because the
checkout was never brought current or because the remote advanced while this
run was writing, and both resolve the same way: move the local branch onto
the remote tip, then let the caller REGENERATE the managed layer on that new
base.

Regeneration — not a merge preference — is what makes the result correct. A
``merge -X theirs`` keeps whatever non-conflicting content the older side
added, so a block this Yoke version no longer renders survives the merge and
the operator cleans it by hand afterwards. Re-running the bundle write on the
updated base produces exactly the content this version renders, and the
managed-block mechanics preserve the operator's own text around it.

Nothing here force-pushes and nothing here rewrites work the operator has not
published. Commits the remote lacks are replaced only when every one of them
is an installer commit; anything else is reported as divergence with its
recovery. The branch move itself goes through ``git switch``, which refuses
rather than overwrite unexpected local modifications.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from yoke_cli.project_install import checkout_gate
from yoke_cli.project_install.files import ProjectInstallError

NETWORK_GIT_TIMEOUT_SECONDS = 120
FALLBACK_REMOTE = "origin"

NOT_A_GIT_CHECKOUT = "not_a_git_checkout"
NO_REMOTE = "no_remote"
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
) -> subprocess.CompletedProcess[str]:
    """Run a git command that talks to the remote, never interactively.

    ``GIT_TERMINAL_PROMPT=0`` turns a missing credential into a named failure
    instead of a command that blocks forever on a prompt no install has a
    terminal for, and the timeout bounds an unreachable host.
    """
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env.setdefault("GIT_ASKPASS", "")
    try:
        return subprocess.run(
            ["git", "-C", str(repo_root), *args],
            capture_output=True,
            text=True,
            check=False,
            env=env,
            timeout=NETWORK_GIT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(
            args=list(args),
            returncode=124,
            stdout="",
            stderr=(
                f"git {args[0] if args else 'remote'} exceeded "
                f"{NETWORK_GIT_TIMEOUT_SECONDS}s against the remote"
            ),
        )


def publish_remote(repo_root: Path, branch: str) -> str | None:
    """Return the remote this branch publishes to, or None when local-only."""
    configured = checkout_gate.run_git(
        repo_root, "config", "--get", f"branch.{branch}.remote",
    ).stdout.strip()
    listed = [
        name
        for name in checkout_gate.run_git(
            repo_root, "remote",
        ).stdout.splitlines()
        if name.strip()
    ]
    if configured and configured in listed:
        return configured
    if FALLBACK_REMOTE in listed:
        return FALLBACK_REMOTE
    return listed[0] if listed else None


def read_remote_state(
    repo_root: Path, *, branch: str, remote: str | None = None,
) -> RemoteState:
    """Fetch the branch's remote ref and classify local against it."""
    if not checkout_gate.is_git_checkout(repo_root):
        return RemoteState(NOT_A_GIT_CHECKOUT)
    resolved = remote or publish_remote(repo_root, branch)
    if not resolved:
        return RemoteState(NO_REMOTE, branch=branch)
    fetched = network_git(repo_root, "fetch", "--quiet", resolved, branch)
    local_sha = _rev_parse(repo_root, branch)
    if fetched.returncode != 0:
        detail = fetched.stderr.strip() or fetched.stdout.strip()
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
    remote_sha = _rev_parse(repo_root, "FETCH_HEAD")
    if not remote_sha or not local_sha:
        return RemoteState(
            FETCH_FAILED,
            remote=resolved,
            branch=branch,
            local_sha=local_sha,
            remote_sha=remote_sha,
            detail="the fetched remote tip or the local branch tip is unreadable",
        )
    if remote_sha == local_sha:
        status = CURRENT
    elif _is_ancestor(repo_root, local_sha, remote_sha):
        status = BEHIND
    elif _is_ancestor(repo_root, remote_sha, local_sha):
        status = AHEAD
    else:
        status = DIVERGED
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


def bring_branch_current(
    repo_root: Path, *, branch: str, remote: str | None = None,
) -> dict[str, Any]:
    """Fast-forward the publish branch onto its remote when it owns no commits.

    The installer's own consumption of the shared project freshness contract:
    generate against the revision the remote actually holds, so the commit
    this run makes is a child of current upstream rather than of a stale base.
    A branch carrying commits the remote lacks is reported, never rewritten.
    """
    on_branch = checkout_gate.current_branch(repo_root)
    if on_branch != branch:
        return {
            "status": "skipped",
            "reason": (
                f"checkout is on {on_branch or 'detached HEAD'}, not the "
                f"publish branch {branch}"
            ),
        }
    state = read_remote_state(repo_root, branch=branch, remote=remote)
    if state.status != BEHIND:
        return state.payload()
    move_branch_onto(repo_root, branch=branch, sha=state.remote_sha)
    return {**state.payload(), "status": "fast_forwarded"}


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


def _is_ancestor(repo_root: Path, ancestor: str, descendant: str) -> bool:
    return checkout_gate.run_git(
        repo_root, "merge-base", "--is-ancestor", ancestor, descendant,
    ).returncode == 0


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
    "NETWORK_GIT_TIMEOUT_SECONDS",
    "NO_REMOTE",
    "NOT_A_GIT_CHECKOUT",
    "REMOTE_BRANCH_MISSING",
    "RemoteState",
    "bring_branch_current",
    "move_branch_onto",
    "network_git",
    "publish_remote",
    "read_remote_state",
    "reconcile_by_regeneration",
]
