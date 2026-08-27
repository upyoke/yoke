"""Client-side binding of environment runs to immutable Git commits."""

from __future__ import annotations

import fcntl
import os
import subprocess
from unittest.mock import patch

import pytest

from yoke_cli.commands.deployment_lineage import (
    DeploymentLineageResolutionError,
    resolve_commit_lineage,
)


def _completed(returncode: int = 0, stdout: str = "", stderr: str = ""):
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr,
    )


def test_resolve_commit_lineage_fetches_and_resolves_the_named_remote_ref(
    tmp_path,
):
    commit = "a" * 40
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    with patch(
        "yoke_cli.commands.deployment_lineage.subprocess.run",
        side_effect=[
            _completed(stdout=f"{tmp_path}\n"),
            _completed(stdout=".git\n"),
            # The fetch reaches a remote, so the credentialed runner first
            # asks the checkout which URL it will contact; an unresolvable
            # remote simply means no GitHub credential is attached.
            _completed(returncode=1),
            _completed(),
            _completed(stdout=f"{commit}\n"),
        ],
    ) as run:
        assert resolve_commit_lineage(str(tmp_path), "origin/stage") == commit

    assert [call.args[0] for call in run.call_args_list] == [
        ["git", "-C", str(tmp_path), "rev-parse", "--show-toplevel"],
        ["git", "-C", str(tmp_path), "rev-parse", "--git-common-dir"],
        ["git", "-C", str(tmp_path), "remote", "get-url", "origin"],
        [
            "git", "-C", str(tmp_path), "fetch", "--quiet", "--no-tags",
            "origin",
        ],
        [
            "git", "-C", str(tmp_path), "rev-parse", "--verify",
            "origin/stage^{commit}",
        ],
    ]
    assert (git_dir / "yoke-deployment-lineage-fetch.lock").exists()


def test_resolve_commit_lineage_holds_checkout_lock_while_fetching(tmp_path):
    commit = "a" * 40
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    lock_path = git_dir / "yoke-deployment-lineage-fetch.lock"

    def fake_git(_repo, *args):
        if args == ("rev-parse", "--show-toplevel"):
            return _completed(stdout=f"{tmp_path}\n")
        if args == ("rev-parse", "--git-common-dir"):
            return _completed(stdout=".git\n")
        if args[0] == "fetch":
            contender = os.open(lock_path, os.O_RDWR)
            try:
                with pytest.raises(BlockingIOError):
                    fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)
            finally:
                os.close(contender)
            return _completed()
        return _completed(stdout=f"{commit}\n")

    with patch(
        "yoke_cli.commands.deployment_lineage._git",
        side_effect=fake_git,
    ):
        assert resolve_commit_lineage(str(tmp_path), "origin/main") == commit


def test_resolve_commit_lineage_refuses_a_non_top_level_checkout():
    with patch(
        "yoke_cli.commands.deployment_lineage.subprocess.run",
        return_value=_completed(stdout="/repo\n"),
    ):
        with pytest.raises(
            DeploymentLineageResolutionError,
            match="must be its Git top-level",
        ):
            resolve_commit_lineage("/repo/subdir", "origin/main")


def test_resolve_commit_lineage_refuses_non_commit_output(tmp_path):
    (tmp_path / ".git").mkdir()
    with patch(
        "yoke_cli.commands.deployment_lineage.subprocess.run",
        side_effect=[
            _completed(stdout=f"{tmp_path}\n"),
            _completed(stdout=".git\n"),
            _completed(returncode=1),  # the fetch's remote-URL probe
            _completed(),
            _completed(stdout="not-a-commit\n"),
        ],
    ):
        with pytest.raises(
            DeploymentLineageResolutionError,
            match="did not resolve to one full commit SHA",
        ):
            resolve_commit_lineage(str(tmp_path), "origin/main")
