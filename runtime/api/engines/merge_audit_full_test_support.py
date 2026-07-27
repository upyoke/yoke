"""Shared repository and database fixtures for merge-audit tests."""

import os
import subprocess

import pytest

from runtime.api.fixtures.file_test_db import init_test_db
from yoke_core.engines.merge_audit_test_schema import apply_merge_audit_schema


@pytest.fixture()
def tmp_db(tmp_path):
    """Backend-aware DB with the merge-audit tables; yields its path.

    ``merge_audit.generate_report`` reads through the backend factory, so the
    schema and seed must land in the same backend (the file on SQLite, the
    repointed per-test database on Postgres).
    """
    with init_test_db(tmp_path, apply_schema=apply_merge_audit_schema) as path:
        yield path


GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "test",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "test",
    "GIT_COMMITTER_EMAIL": "t@t",
}


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
        env=GIT_ENV,
    )
    subprocess.run(
        ["git", "-C", str(repo), "branch", "-M", "main"],
        capture_output=True,
        check=True,
    )
    return str(repo)


def _add_branch(repo: str, name: str, num_commits: int = 1) -> None:
    """Create a branch with commits ahead of main."""
    subprocess.run(
        ["git", "-C", repo, "checkout", "-b", name],
        capture_output=True,
        check=True,
    )
    for i in range(num_commits):
        subprocess.run(
            [
                "git",
                "-C",
                repo,
                "commit",
                "--allow-empty",
                "-m",
                f"work {i + 1} on {name}",
            ],
            capture_output=True,
            check=True,
            env=GIT_ENV,
        )
    subprocess.run(
        ["git", "-C", repo, "checkout", "main"],
        capture_output=True,
        check=True,
    )


def _env(tmp_db, fake_repo):
    return {"YOKE_DB": tmp_db, "MERGE_AUDIT_REPO_ROOT": fake_repo}
