"""Client-side binding of environment runs to immutable Git commits."""

from __future__ import annotations

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


def test_resolve_commit_lineage_fetches_and_resolves_the_named_remote_ref():
    commit = "a" * 40
    with patch(
        "yoke_cli.commands.deployment_lineage.subprocess.run",
        side_effect=[
            _completed(stdout="/repo\n"),
            _completed(),
            _completed(stdout=f"{commit}\n"),
        ],
    ) as run:
        assert resolve_commit_lineage("/repo", "origin/stage") == commit

    assert [call.args[0] for call in run.call_args_list] == [
        ["git", "-C", "/repo", "rev-parse", "--show-toplevel"],
        ["git", "-C", "/repo", "fetch", "--quiet", "--no-tags", "origin"],
        [
            "git", "-C", "/repo", "rev-parse", "--verify",
            "origin/stage^{commit}",
        ],
    ]


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


def test_resolve_commit_lineage_refuses_non_commit_output():
    with patch(
        "yoke_cli.commands.deployment_lineage.subprocess.run",
        side_effect=[
            _completed(stdout="/repo\n"),
            _completed(),
            _completed(stdout="not-a-commit\n"),
        ],
    ):
        with pytest.raises(
            DeploymentLineageResolutionError,
            match="did not resolve to one full commit SHA",
        ):
            resolve_commit_lineage("/repo", "origin/main")
