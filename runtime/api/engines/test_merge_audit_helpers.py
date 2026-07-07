"""Tests for yoke_core.engines.merge_audit git helpers and CLI."""

from __future__ import annotations

import sys
import os
import subprocess

import pytest

from yoke_core.engines import merge_audit
from runtime.api.source_pythonpath_test_helpers import SOURCE_PYTHONPATH


@pytest.fixture()
def tmp_db(tmp_path):
    """Hold a disposable Postgres DB open for CLI subprocess tests."""
    from runtime.api.fixtures import pg_testdb

    with pg_testdb.test_database():
        yield


@pytest.fixture()
def fake_repo(tmp_path):
    """Create a fake git repo with main branch."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "--allow-empty", "-m", "init"],
        capture_output=True, check=True,
        env={**os.environ, "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "t@t",
             "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "t@t"},
    )
    subprocess.run(
        ["git", "-C", str(repo), "branch", "-M", "main"],
        capture_output=True, check=True,
    )
    return str(repo)


def _add_branch(repo: str, name: str) -> None:
    """Create a branch with one commit ahead of main."""
    env = {**os.environ, "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "t@t"}
    subprocess.run(
        ["git", "-C", repo, "checkout", "-b", name],
        capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "-C", repo, "commit", "--allow-empty", "-m", f"work on {name}"],
        capture_output=True, check=True, env=env,
    )
    subprocess.run(
        ["git", "-C", repo, "checkout", "main"],
        capture_output=True, check=True,
    )


class TestGitHelpers:
    """Test git helper functions."""

    def test_branch_exists_false(self, fake_repo):
        assert not merge_audit._branch_exists(fake_repo, "nonexistent")

    def test_branch_exists_true(self, fake_repo):
        _add_branch(fake_repo, "test-branch")
        assert merge_audit._branch_exists(fake_repo, "test-branch")

    def test_commits_ahead(self, fake_repo):
        _add_branch(fake_repo, "ahead-branch")
        count = merge_audit._commits_ahead(fake_repo, "ahead-branch")
        assert count == 1

    def test_commits_ahead_nonexistent(self, fake_repo):
        count = merge_audit._commits_ahead(fake_repo, "nope")
        assert count == 0

    def test_list_sun_branches(self, fake_repo):
        _add_branch(fake_repo, "YOK-99")
        _add_branch(fake_repo, "YOK-100")
        _add_branch(fake_repo, "other-branch")
        branches = merge_audit._list_sun_branches(fake_repo)
        assert "YOK-99" in branches
        assert "YOK-100" in branches
        assert "other-branch" not in branches


class TestCLI:
    """Test CLI argument parsing."""

    def test_invalid_epic_id(self, fake_repo):
        """Invalid epic ID produces error and exit 1."""
        result = subprocess.run(
            [sys.executable, "-m", "yoke_core.engines.merge_audit", "notanumber"],
            capture_output=True, text=True,
            cwd=str(fake_repo),
            env={**os.environ, "MERGE_AUDIT_REPO_ROOT": fake_repo,
                 "PYTHONPATH": SOURCE_PYTHONPATH},
        )
        assert result.returncode == 1
        assert "invalid epic ID" in result.stderr

    def test_sun_prefix_stripped(self, tmp_db, fake_repo):
        """YOK- prefix is stripped from epic ID argument."""
        env = {
            **os.environ,
            "MERGE_AUDIT_REPO_ROOT": fake_repo,
            "PYTHONPATH": SOURCE_PYTHONPATH,
        }
        result = subprocess.run(
            [sys.executable, "-m", "yoke_core.engines.merge_audit", "YOK-42"],
            capture_output=True, text=True,
            cwd=str(fake_repo),
            env=env,
        )
        assert result.returncode == 0
        assert "No unmerged branches found for epic 42." in result.stdout
