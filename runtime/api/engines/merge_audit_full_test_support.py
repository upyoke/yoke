"""Shared repository and database fixtures for merge-audit tests."""

import os
import subprocess

import pytest

from runtime.api.fixtures.file_test_db import init_test_db
from runtime.api.engines.merge_audit_test_seeds import seed_merge_audit_item
from runtime.api.fixtures.file_test_db import connect_test_db


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    """Production-schema DB holding items YOK-42 and YOK-999; yields its path.

    ``merge_audit.generate_report`` reads through the backend factory, so the
    seed lands in the repointed per-test database it reads.
    """
    monkeypatch.setenv("YOKE_PROJECT", "yoke")
    with init_test_db(tmp_path) as path:
        conn = connect_test_db(path)
        try:
            for item_id in (42, 999):
                seed_merge_audit_item(
                    conn, item_id=item_id, title="No active lanes", status="idea"
                )
            conn.commit()
        finally:
            conn.close()
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
