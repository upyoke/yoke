"""Reading git's own record of which worktrees exist and where.

Both lane-retirement boundaries and the merge preparation path start from the
same question — what does git currently have checked out, and which of those
directories did Yoke create — so they read it through here rather than each
parsing ``git worktree list`` their own way.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class RegisteredWorktree:
    """One branch-bearing worktree as git reports it."""

    path: Path
    branch: str
    # Git's lock note; ``None`` when the worktree is not locked.
    lock_reason: str | None = None


def first_output_line(result: Any) -> str:
    """The first meaningful line git wrote, or its exit code."""
    detail = (result.stderr or result.stdout or "").strip()
    return detail.splitlines()[0] if detail else f"exit {result.returncode}"


def registered_worktrees(
    run_git: Callable[..., Any], repo_root: str
) -> list[RegisteredWorktree] | None:
    """Every branch-bearing worktree git registers, or ``None`` when it cannot say."""
    result = run_git(["worktree", "list", "--porcelain"], cwd=repo_root, capture=True)
    if result.returncode != 0:
        return None
    entries: list[RegisteredWorktree] = []
    block: dict[str, str] = {}
    for line in [*result.stdout.splitlines(), ""]:
        if not line:
            if "branch" in block:
                entries.append(
                    RegisteredWorktree(
                        Path(block["worktree"]).resolve(),
                        block["branch"],
                        block.get("locked"),
                    )
                )
            block = {}
        elif line.startswith("worktree "):
            block["worktree"] = line.removeprefix("worktree ")
        elif line.startswith("branch refs/heads/"):
            block["branch"] = line.removeprefix("branch refs/heads/")
        elif line == "locked" or line.startswith("locked "):
            block["locked"] = line.removeprefix("locked").strip()
    return entries


def is_managed_worktree_path(path: Path, repo_root: Path) -> bool:
    """Whether ``path`` sits under a root Yoke creates lanes in."""
    roots = (repo_root / ".worktrees", repo_root / ".claude" / "worktrees")
    return any(path != root and path.is_relative_to(root) for root in roots)


__all__ = [
    "RegisteredWorktree",
    "first_output_line",
    "is_managed_worktree_path",
    "registered_worktrees",
]
