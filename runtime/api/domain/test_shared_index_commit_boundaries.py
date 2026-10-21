"""A staged deletion is invisible to the ordinary dirty-tree probes.

Every process inside one linked worktree shares that worktree's index.
A staged deletion has no working-tree counterpart, so the probes that
look for modified and untracked files both come back empty and the tree
reads as clean. The merge preflight in ``merge_worktree_prepare_preflight``
therefore also reads ``git diff --cached --name-only``.
"""

from __future__ import annotations

import subprocess

import pytest


def _git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "lane"
    path.mkdir()
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "test@example.invalid")
    _git(path, "config", "user.name", "Test")
    (path / "kept.py").write_text("original\n", encoding="utf-8")
    (path / "also_kept.py").write_text("original\n", encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "seed")
    return path


class TestStagedDeletionIsVisible:
    def test_staged_deletion_leaves_no_working_tree_trace(self, repo):
        """The premise: why the two ordinary probes miss it."""
        _git(repo, "rm", "-q", "kept.py")
        assert _git(repo, "diff", "--name-only").stdout.strip() == ""
        assert _git(
            repo, "ls-files", "--others", "--exclude-standard",
        ).stdout.strip() == ""
        # Only the index knows.
        assert _git(
            repo, "diff", "--cached", "--name-only",
        ).stdout.strip() == "kept.py"

