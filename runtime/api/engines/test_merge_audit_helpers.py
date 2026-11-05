"""Tests for yoke_core.engines.merge_audit git helpers and CLI."""

from __future__ import annotations

import sys
import os
import subprocess

import pytest

from runtime.api.source_pythonpath_test_helpers import SOURCE_PYTHONPATH


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    """Hold a disposable Postgres DB open for CLI subprocess tests.

    Seeds item 42 so PREFIX-N refs resolve through the project
    sequence in subprocess invocations.
    """
    monkeypatch.setenv("YOKE_PROJECT", "yoke")
    from runtime.api.fixtures import pg_testdb
    from runtime.api.fixtures.backlog import insert_item

    with pg_testdb.test_database() as conn:
        insert_item(conn, id=42, title="epic under audit", project="yoke")
        conn.commit()
        yield


@pytest.fixture()
def fake_repo(tmp_path):
    """Create a fake git repo with main branch."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "--allow-empty", "-m", "init"],
        capture_output=True,
        check=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "test",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "test",
            "GIT_COMMITTER_EMAIL": "t@t",
        },
    )
    subprocess.run(
        ["git", "-C", str(repo), "branch", "-M", "main"],
        capture_output=True,
        check=True,
    )
    return str(repo)


def _add_branch(repo: str, name: str) -> None:
    """Create a branch with one commit ahead of main."""
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "test",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "test",
        "GIT_COMMITTER_EMAIL": "t@t",
    }
    subprocess.run(
        ["git", "-C", repo, "checkout", "-b", name],
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "-C", repo, "commit", "--allow-empty", "-m", f"work on {name}"],
        capture_output=True,
        check=True,
        env=env,
    )
    subprocess.run(
        ["git", "-C", repo, "checkout", "main"],
        capture_output=True,
        check=True,
    )


class TestCLI:
    """Test CLI argument parsing."""

    def test_invalid_epic_id(self, fake_repo):
        """Invalid epic ID produces error and exit 1."""
        result = subprocess.run(
            [sys.executable, "-m", "yoke_core.engines.merge_audit", "notanumber"],
            capture_output=True,
            text=True,
            cwd=str(fake_repo),
            env={
                **os.environ,
                "MERGE_AUDIT_REPO_ROOT": fake_repo,
                "PYTHONPATH": SOURCE_PYTHONPATH,
            },
        )
        assert result.returncode == 1
        assert "invalid epic ID" in result.stderr

    def test_prefix_ref_resolves_project_sequence(self, tmp_db, fake_repo):
        """A PREFIX-N epic ref resolves through the project sequence."""
        env = {
            **os.environ,
            "MERGE_AUDIT_REPO_ROOT": fake_repo,
            "PYTHONPATH": SOURCE_PYTHONPATH,
        }
        result = subprocess.run(
            [sys.executable, "-m", "yoke_core.engines.merge_audit", "YOK-42"],
            capture_output=True,
            text=True,
            cwd=str(fake_repo),
            env=env,
        )
        assert result.returncode == 0
        assert "No unmerged branches found for epic YOK-42." in result.stdout
