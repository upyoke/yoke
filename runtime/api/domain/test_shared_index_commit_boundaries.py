"""Commit boundaries must not absorb index entries they did not stage.

Every process inside one linked worktree shares that worktree's index.
So a staged entry is not evidence that the committing agent staged it,
and the two surfaces that turn an index into a commit both have to
account for that.

A staged deletion is the sharp case: it has no working-tree
counterpart, so the probes that look for modified and untracked files
both come back empty and the tree reads as clean.
"""

from __future__ import annotations

import subprocess

import pytest

from yoke_core.domain.agent_stop_commit import auto_commit_worktree


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


class TestAutoCommitRefusesForeignIndexEntries:
    def test_pre_staged_entry_blocks_the_commit(self, repo):
        _git(repo, "rm", "-q", "kept.py")
        head_before = _git(repo, "rev-parse", "HEAD").stdout.strip()

        result = auto_commit_worktree(str(repo), "test-item")

        assert result.committed is False
        assert result.pre_staged == ("kept.py",)
        assert _git(repo, "rev-parse", "HEAD").stdout.strip() == head_before
        # The deletion is still staged, not silently discarded — the net
        # declines to act, it does not clean up after another process.
        assert _git(
            repo, "diff", "--cached", "--name-only",
        ).stdout.strip() == "kept.py"

    def test_own_unstaged_work_still_commits(self, repo):
        (repo / "also_kept.py").write_text("edited\n", encoding="utf-8")
        result = auto_commit_worktree(str(repo), "test-item")
        assert result.committed is True
        assert result.pre_staged == ()
        assert _git(repo, "status", "--porcelain").stdout.strip() == ""

    def test_clean_worktree_commits_nothing(self, repo):
        result = auto_commit_worktree(str(repo), "test-item")
        assert result.committed is False
        assert result.pre_staged == ()
