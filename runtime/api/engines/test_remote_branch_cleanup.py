"""Safety proofs for remote branch cleanup."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest import mock

from yoke_core.engines.remote_branch_cleanup import (
    delete_remote_branch_if_merged,
)


TEST_ITEM_ID = 42
TEST_ITEM_REF = f"YOK-{TEST_ITEM_ID}"


def _completed(returncode: int = 0, stdout: str = ""):
    return mock.Mock(returncode=returncode, stdout=stdout, stderr="")


def test_delete_uses_exact_ref_refreshed_ancestry_and_lease():
    commands: list[list[str]] = []
    responses = iter(
        (
            _completed(),
            _completed(),
            _completed(stdout=f"branch-sha\trefs/heads/{TEST_ITEM_REF}\n"),
            _completed(),
            _completed(),
            _completed(stdout="branch-sha\n"),
            _completed(stdout="target-sha\n"),
            _completed(),
            _completed(),
        )
    )

    def run_git(command):
        commands.append(command)
        return next(responses)

    result = delete_remote_branch_if_merged(
        run_git=run_git,
        branch=TEST_ITEM_REF,
        target_branch="main",
    )

    assert result.status == "deleted"
    assert [
        "ls-remote",
        "--heads",
        "origin",
        f"refs/heads/{TEST_ITEM_REF}",
    ] in commands
    assert [
        "fetch",
        "origin",
        "+refs/heads/main:refs/remotes/origin/main",
    ] in commands
    assert [
        "fetch",
        "origin",
        f"+refs/heads/{TEST_ITEM_REF}:refs/remotes/origin/{TEST_ITEM_REF}",
    ] in commands
    assert [
        "merge-base",
        "--is-ancestor",
        "branch-sha",
        "target-sha",
    ] in commands
    assert commands[-1] == [
        "push",
        f"--force-with-lease=refs/heads/{TEST_ITEM_REF}:branch-sha",
        "origin",
        f":refs/heads/{TEST_ITEM_REF}",
    ]


def test_ambiguous_remote_advertisement_is_preserved_without_delete():
    commands: list[list[str]] = []
    responses = iter(
        (
            _completed(),
            _completed(),
            _completed(stdout=f"sha\trefs/heads/{TEST_ITEM_REF}0\n"),
        )
    )

    def run_git(command):
        commands.append(command)
        return next(responses)

    result = delete_remote_branch_if_merged(
        run_git=run_git,
        branch=TEST_ITEM_REF,
        target_branch="main",
    )

    assert result.status == "preserved"
    assert "ambiguous" in result.reason
    assert not any(command[0] == "push" for command in commands)


def _git(path: Path, *args: str, check: bool = True):
    return subprocess.run(
        ["git", "-C", str(path), *args],
        check=check,
        capture_output=True,
        text=True,
    )


def test_concurrent_remote_update_survives_leased_delete(tmp_path: Path):
    origin = tmp_path / "origin.git"
    repo = tmp_path / "repo"
    subprocess.run(
        ["git", "init", "--bare", "--initial-branch=main", str(origin)],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "init", "--initial-branch=main", str(repo)],
        check=True,
        capture_output=True,
        text=True,
    )
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "base")
    _git(repo, "remote", "add", "origin", str(origin))
    _git(repo, "push", "origin", "main")
    _git(repo, "branch", TEST_ITEM_REF)
    _git(repo, "push", "origin", TEST_ITEM_REF)

    concurrent_sha = ""

    def run_git(command):
        nonlocal concurrent_sha
        if command[0] == "push" and any(
            value.startswith("--force-with-lease=") for value in command
        ):
            head = _git(repo, "rev-parse", TEST_ITEM_REF).stdout.strip()
            tree = _git(repo, "rev-parse", f"{TEST_ITEM_REF}^{{tree}}").stdout.strip()
            concurrent_sha = subprocess.run(
                ["git", "-C", str(repo), "commit-tree", tree, "-p", head],
                input="concurrent remote work\n",
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            _git(
                repo,
                "push",
                "origin",
                f"{concurrent_sha}:refs/heads/{TEST_ITEM_REF}",
            )
        return _git(repo, *command, check=False)

    result = delete_remote_branch_if_merged(
        run_git=run_git,
        branch=TEST_ITEM_REF,
        target_branch="main",
    )

    assert result.status == "preserved"
    assert "refused" in result.reason
    advertised = _git(repo, "ls-remote", "origin", f"refs/heads/{TEST_ITEM_REF}")
    assert advertised.stdout.split()[0] == concurrent_sha
