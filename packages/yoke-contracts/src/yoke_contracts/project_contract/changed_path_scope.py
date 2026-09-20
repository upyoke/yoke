"""One working-tree changed-path derivation for local mirrors of CI contracts.

A local check that mirrors a required CI contract earns its keep only when a
green result predicts CI. ``git diff`` reports tracked content and nothing
else, so a changed set built from it alone cannot see a file that has been
authored but not yet added -- and a brand-new file is the likeliest place for
a fresh violation to sit. A mirror with that blind spot does not merely miss
things: it turns "I verified" into a false statement, most often for exactly
the files a change just introduced.

The set derived here is what a commit of this tree would hand to CI: tracked
changes measured from the base, plus untracked paths Git would add. Two
categories stay out on purpose and are named wherever the set is reported:

* Ignored paths. Git will never commit them, so CI never sees them either.
  Leaving them out is agreement with the CI contract, not an exclusion from it.
* Deletions. A removed file has no content to check on either side.

An untracked path that is never committed makes this set a superset of the one
CI derives. That direction is deliberate: it can only cost a local red that CI
would have passed, never a local green that CI fails.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

#: Git status letters every mirror selects on: added, copied, modified,
#: renamed, type-changed. Deletions are absent because a removed file has no
#: content to check. CI's own contract scope uses the same letters without
#: ``T``; keeping ``T`` here only widens the local side.
CHANGE_FILTER = "ACMRT"


class ChangedPathError(RuntimeError):
    """Raised when Git cannot resolve the changed-path set."""

    def __init__(self, returncode: int, detail: str) -> None:
        super().__init__(detail)
        self.returncode = returncode


@dataclass(frozen=True)
class WorkingTreeChangedPaths:
    """Tracked and untracked halves of one working tree's changed set."""

    tracked: tuple[str, ...]
    untracked: tuple[str, ...]

    @property
    def paths(self) -> tuple[str, ...]:
        """Both halves, tracked first, with order preserved and no repeats."""
        merged: list[str] = list(self.tracked)
        seen = set(merged)
        for path in self.untracked:
            if path not in seen:
                seen.add(path)
                merged.append(path)
        return tuple(merged)

    def coverage_sentence(self, *, noun: str = "path") -> str:
        """Name what this set covers and what it deliberately leaves out."""
        tracked_noun = noun if len(self.tracked) == 1 else f"{noun}s"
        untracked_noun = noun if len(self.untracked) == 1 else f"{noun}s"
        return (
            f"scope: {len(self.tracked)} tracked {tracked_noun} changed from "
            f"the base plus {len(self.untracked)} untracked {untracked_noun} "
            "Git would add; ignored paths and deletions stay out because CI "
            "never sees them either"
        )


def _git_output(repo_root: Path, arguments: Sequence[str]) -> bytes:
    completed = subprocess.run(
        ["git", "-C", str(repo_root), *arguments],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode:
        detail = os.fsdecode(completed.stderr).strip()
        raise ChangedPathError(completed.returncode, detail)
    return completed.stdout


def _nul_separated(raw: bytes) -> tuple[str, ...]:
    """Decode a ``-z`` Git listing, preserving unusual filenames verbatim."""
    return tuple(
        os.fsdecode(entry) for entry in raw.split(b"\0") if entry
    )


def tracked_changed_paths(repo_root: Path, base_rev: str) -> tuple[str, ...]:
    """Tracked paths differing from *base_rev* through the working tree.

    The one-revision ``git diff`` form compares the base with the working
    tree, so committed, staged, and unstaged tracked edits all land here.
    Never reach for the three-dot form: it degenerates to empty when the base
    is HEAD, which silently reports every check as having nothing to do.
    """
    return _nul_separated(
        _git_output(
            repo_root,
            ("diff", "--name-only", "-z", f"--diff-filter={CHANGE_FILTER}",
             base_rev, "--"),
        )
    )


def untracked_paths(repo_root: Path) -> tuple[str, ...]:
    """Untracked, non-ignored paths -- the ones a commit would newly add."""
    return _nul_separated(
        _git_output(
            repo_root, ("ls-files", "--others", "--exclude-standard", "-z"),
        )
    )


def staged_changed_paths(repo_root: Path) -> tuple[str, ...]:
    """Paths already staged for the next commit.

    A staged set needs no untracked half: ``git add`` is what moves a new file
    into it, so what is staged is exactly what the commit will carry.
    """
    return _nul_separated(
        _git_output(
            repo_root,
            ("diff", "--cached", "--name-only", "-z",
             f"--diff-filter={CHANGE_FILTER}"),
        )
    )


def working_tree_changed_paths(
    repo_root: Path, base_rev: str,
) -> WorkingTreeChangedPaths:
    """Everything a commit of this tree would carry to CI, measured from a base."""
    return WorkingTreeChangedPaths(
        tracked=tracked_changed_paths(repo_root, base_rev),
        untracked=untracked_paths(repo_root),
    )


def changed_scope_for_check(
    repo_root: Path, base: str | None, *, staged: bool,
) -> WorkingTreeChangedPaths:
    """The set a local mirror of a CI contract should evaluate.

    A staged run needs no untracked half — ``git add`` is what puts a new file
    into the commit, so the staged set is already exact. Every other run reads
    the working tree, where an authored-but-not-yet-added file lives.
    """
    if staged:
        return WorkingTreeChangedPaths(staged_changed_paths(repo_root), ())
    return working_tree_changed_paths(repo_root, base or "main")


__all__ = [
    "CHANGE_FILTER",
    "ChangedPathError",
    "WorkingTreeChangedPaths",
    "changed_scope_for_check",
    "staged_changed_paths",
    "tracked_changed_paths",
    "untracked_paths",
    "working_tree_changed_paths",
]
