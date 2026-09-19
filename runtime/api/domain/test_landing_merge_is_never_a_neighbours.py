"""A branch that carried nothing in is handed no landing merge.

Resolving the landing by bisecting the base's first-parent chain finds the
oldest commit holding the branch. When the branch never advanced past the
trunk commit it forked from, every commit on that chain after it holds it,
so the bisect lands on whatever came next -- which belongs to somebody
else. The boundary alone cannot tell the two apart, because the question
is not "which commit first held this" but "which merge carried it in", and
a commit already on the trunk was never carried anywhere.

The discriminator is the candidate's own first parent: when it already
holds the commit, the candidate did not bring it in.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from yoke_core.domain import item_merge_receipts as receipts


def _repo(tmp_path: Path):
    root = tmp_path / "neighbour-merge"
    root.mkdir()

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(root), *args],
            check=True, capture_output=True, text=True,
        ).stdout.strip()

    git("init", "-b", "main")
    git("config", "user.email", "test@test.com")
    git("config", "user.name", "Test")
    (root / "base.txt").write_text("base\n")
    git("add", "base.txt")
    git("commit", "-m", "base")
    forked_from = git("rev-parse", "HEAD")

    # A neighbour lands a real merge onto main straight after that commit.
    # The item's branch sits at forked_from and contributed nothing.
    git("checkout", "-b", "neighbour")
    (root / "neighbour.txt").write_text("neighbour\n")
    git("add", "neighbour.txt")
    git("commit", "-m", "neighbour work")
    git("checkout", "main")
    git("merge", "--no-ff", "--no-edit", "neighbour")
    neighbour_merge = git("rev-parse", "HEAD")
    return root, forked_from, neighbour_merge, git


def test_a_branch_at_the_trunk_commit_resolves_no_landing(tmp_path: Path) -> None:
    root, forked_from, neighbour_merge, _git = _repo(tmp_path)

    resolved = receipts.landing_merge_commit(str(root), "main", forked_from)

    assert resolved == ""
    assert resolved != neighbour_merge


def test_the_neighbours_merge_would_otherwise_be_the_boundary(
    tmp_path: Path,
) -> None:
    """Pins why the boundary alone is not enough: it does hold the commit."""
    root, forked_from, neighbour_merge, _git = _repo(tmp_path)

    assert receipts.git.is_ancestor(str(root), forked_from, neighbour_merge)
    # And its first parent holds it too, which is what says it carried
    # nothing in -- the trunk already had the commit before this merge.
    assert receipts.git.is_ancestor(
        str(root), forked_from, f"{neighbour_merge}^1"
    )


def test_a_branch_that_did_advance_still_resolves_its_own_merge(
    tmp_path: Path,
) -> None:
    """The guard must not swallow a real landing."""
    root, _forked_from, neighbour_merge, git = _repo(tmp_path)
    neighbour_head = git("rev-parse", "neighbour")

    resolved = receipts.landing_merge_commit(str(root), "main", neighbour_head)

    assert resolved == neighbour_merge
