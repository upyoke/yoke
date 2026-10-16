"""Reading git's own record of which worktrees exist and where.

Both lane-retirement boundaries and the merge preparation path start from the
same question — what does git currently have checked out, and which of those
directories did Yoke create — so they read it through here rather than each
parsing ``git worktree list`` their own way. A detached checkout is
``detached@<commit>``, never an empty branch.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


# A detached checkout has no branch line. Callers used to substitute ``""``,
# and one empty branch rejected an entire prune batch. The marker keeps the
# commit that is actually checked out so landing proof can read it.
DETACHED_PREFIX = "detached@"


def detached_lane_branch(head: str) -> str:
    """Identity of a worktree git has checked out with no branch."""
    return f"{DETACHED_PREFIX}{head}"


def detached_head(branch: str) -> str:
    """The commit a detached-lane marker names, or ``""`` for a real branch."""
    if not branch.startswith(DETACHED_PREFIX):
        return ""
    return branch[len(DETACHED_PREFIX) :]


@dataclass(frozen=True)
class ParsedWorktree:
    """One worktree as ``git worktree list --porcelain`` reported it.

    ``branch`` is the checked-out branch, ``detached@<commit>`` when git
    reports ``detached`` and a ``HEAD``, or ``""`` when the record names
    neither. An empty branch is not a detached checkout.
    """

    path: str
    branch: str
    lock_reason: str | None = None


@dataclass(frozen=True)
class RegisteredWorktree:
    """One worktree git registers with a branch or a detached commit."""

    path: Path
    branch: str
    # Git's lock note; ``None`` when the worktree is not locked.
    lock_reason: str | None = None


def first_output_line(result: Any) -> str:
    """The first meaningful line git wrote, or its exit code."""
    detail = (result.stderr or result.stdout or "").strip()
    return detail.splitlines()[0] if detail else f"exit {result.returncode}"


def parse_worktree_porcelain(stdout: str) -> list[ParsedWorktree]:
    """Every worktree block in porcelain, including a detached checkout.

    A detached block is ``detached@<HEAD>``. A block with neither a branch
    nor a detached HEAD keeps ``branch=""`` so a caller can report that one
    record without inventing an identity for it.
    """
    entries: list[ParsedWorktree] = []
    block: dict[str, str] = {}
    for line in [*stdout.splitlines(), ""]:
        if not line:
            if "worktree" in block:
                if "branch" in block:
                    branch = block["branch"]
                elif block.get("detached") == "1" and block.get("head"):
                    branch = detached_lane_branch(block["head"])
                else:
                    branch = ""
                entries.append(
                    ParsedWorktree(
                        block["worktree"],
                        branch,
                        block.get("locked"),
                    )
                )
            block = {}
            continue
        if line.startswith("worktree "):
            block["worktree"] = line.removeprefix("worktree ")
        elif line.startswith("HEAD "):
            block["head"] = line.removeprefix("HEAD ").strip()
        elif line.startswith("branch refs/heads/"):
            block["branch"] = line.removeprefix("branch refs/heads/")
        elif line == "detached":
            block["detached"] = "1"
        elif line == "locked" or line.startswith("locked "):
            block["locked"] = line.removeprefix("locked").strip()
    return entries


def registered_worktrees(
    run_git: Callable[..., Any], repo_root: str
) -> list[RegisteredWorktree] | None:
    """Every worktree with a branch or detached commit, or ``None`` when unread.

    A record that names neither is omitted. Callers that need to report it
    read :func:`parse_worktree_porcelain` themselves.
    """
    result = run_git(["worktree", "list", "--porcelain"], cwd=repo_root, capture=True)
    if result.returncode != 0:
        return None
    return [
        RegisteredWorktree(Path(entry.path).resolve(), entry.branch, entry.lock_reason)
        for entry in parse_worktree_porcelain(result.stdout or "")
        if entry.branch
    ]


def is_managed_worktree_path(path: Path, repo_root: Path) -> bool:
    """Whether ``path`` sits under a root Yoke creates lanes in."""
    roots = (repo_root / ".worktrees", repo_root / ".claude" / "worktrees")
    return any(path != root and path.is_relative_to(root) for root in roots)


__all__ = [
    "DETACHED_PREFIX",
    "ParsedWorktree",
    "RegisteredWorktree",
    "detached_head",
    "detached_lane_branch",
    "first_output_line",
    "is_managed_worktree_path",
    "parse_worktree_porcelain",
    "registered_worktrees",
]
