"""Conservatively advance a project's main checkout after a landing."""

from __future__ import annotations

import subprocess
from typing import Callable, Optional

from yoke_cli.config import credentialed_git


Runner = Callable[..., subprocess.CompletedProcess[str]]


def _git(
    repo_root: str,
    args: tuple[str, ...],
    *,
    run: Optional[Runner],
) -> subprocess.CompletedProcess[str]:
    if run is not None:
        return run(
            ["git", "-C", repo_root, *args],
            capture_output=True,
            text=True,
            check=False,
        )
    return credentialed_git.run(["-C", repo_root, *args])


def origin_default_branch(repo_root: str, *, run: Optional[Runner] = None) -> str:
    """Return the branch ``origin/HEAD`` names, or empty if unknown."""
    ref = _git(
        repo_root, ("symbolic-ref", "--short", "refs/remotes/origin/HEAD"), run=run
    )
    if ref.returncode != 0:
        return ""
    current = ref.stdout.strip()
    prefix = "origin/"
    return current[len(prefix):] if current.startswith(prefix) else current


def fast_forward_main_checkout(
    repo_root: str,
    target: str,
    *,
    run: Optional[Runner] = None,
) -> str:
    """Fast-forward a checkout on ``target``; return an advisory.

    A landed merge is never unwound by local-checkout state. The mutation is
    ``pull --ff-only`` after the checkout is on ``target`` and has no
    tracked local changes. Untracked files are left for git: they only
    fail the pull when an incoming commit would overwrite one, and that
    failure is returned as the advisory.
    """
    branch = _git(repo_root, ("branch", "--show-current"), run=run)
    current = branch.stdout.strip() if branch.returncode == 0 else ""
    if current != target:
        reason = f"checkout is on {current or 'detached HEAD'}, not {target}"
        return f"main checkout not fast-forwarded: {reason}"

    status = _git(
        repo_root, ("status", "--porcelain", "--untracked-files=no"), run=run
    )
    if status.returncode != 0:
        return "main checkout not fast-forwarded: cleanliness could not be read"
    if status.stdout.strip():
        return "main checkout not fast-forwarded: checkout has local changes"

    pulled = _git(repo_root, ("pull", "--ff-only", "origin", target), run=run)
    if pulled.returncode == 0:
        return ""
    detail = (pulled.stderr or pulled.stdout).strip().splitlines()
    reason = detail[-1] if detail else "git pull --ff-only failed"
    return f"main checkout not fast-forwarded: {reason}"


def sync_main_checkout_at_session_start(
    repo_root: str,
    *,
    run: Optional[Runner] = None,
) -> str:
    """Advance the default-branch checkout once; never raise."""
    if not repo_root:
        return "main checkout not fast-forwarded: checkout root is missing"
    target = origin_default_branch(repo_root, run=run)
    if not target:
        return "main checkout not fast-forwarded: origin default branch unknown"
    return fast_forward_main_checkout(repo_root, target, run=run)


__all__ = [
    "fast_forward_main_checkout",
    "origin_default_branch",
    "sync_main_checkout_at_session_start",
]
