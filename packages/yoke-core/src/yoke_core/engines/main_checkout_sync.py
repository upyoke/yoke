"""Conservatively advance a project's main checkout after a landing."""

from __future__ import annotations

import subprocess
from typing import Callable, Optional


Runner = Callable[..., subprocess.CompletedProcess[str]]


def fast_forward_main_checkout(
    repo_root: str,
    target: str,
    *,
    run: Optional[Runner] = None,
) -> str:
    """Fast-forward a clean checkout on ``target``; return an advisory.

    A landed merge is never unwound by local-checkout state. The mutation is
    deliberately limited to ``pull --ff-only`` after read-only branch and
    cleanliness checks prove that updating the working tree is safe.
    """
    execute = run or subprocess.run

    def git(*args: str) -> subprocess.CompletedProcess[str]:
        return execute(
            ["git", "-C", repo_root, *args],
            capture_output=True,
            text=True,
            check=False,
        )

    branch = git("branch", "--show-current")
    current = branch.stdout.strip() if branch.returncode == 0 else ""
    if current != target:
        reason = f"checkout is on {current or 'detached HEAD'}, not {target}"
        return f"main checkout not fast-forwarded: {reason}"

    status = git("status", "--porcelain", "--untracked-files=all")
    if status.returncode != 0:
        return "main checkout not fast-forwarded: cleanliness could not be read"
    if status.stdout.strip():
        return "main checkout not fast-forwarded: checkout has local changes"

    pulled = git("pull", "--ff-only", "origin", target)
    if pulled.returncode == 0:
        return ""
    detail = (pulled.stderr or pulled.stdout).strip().splitlines()
    reason = detail[-1] if detail else "git pull --ff-only failed"
    return f"main checkout not fast-forwarded: {reason}"


__all__ = ["fast_forward_main_checkout"]
