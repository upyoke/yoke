"""Authenticated push upstream tracking is restored with compare-and-swap."""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from yoke_cli.config import project_git_upstream
from yoke_cli.config.project_onboard_support import ProjectOnboardError


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=root, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
    )
    return result.stdout.strip()


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "--initial-branch", "main")
    _git(root, "config", "branch.main.remote", "previous")
    _git(root, "config", "branch.main.merge", "refs/heads/previous")
    return root


def test_failed_push_restores_the_exact_values_it_installed(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    snapshot = project_git_upstream.configure(
        root, remote="origin", branch="main",
    )

    project_git_upstream.restore(root, snapshot)

    assert _git(root, "config", "branch.main.remote") == "previous"
    assert _git(root, "config", "branch.main.merge") == "refs/heads/previous"


@pytest.mark.parametrize(
    ("key", "concurrent_value"),
    [
        ("branch.main.remote", "concurrent-remote"),
        ("branch.main.merge", "refs/heads/concurrent"),
    ],
)
def test_failed_push_never_clobbers_concurrent_upstream_change(
    tmp_path: Path, key: str, concurrent_value: str,
) -> None:
    root = _repo(tmp_path)
    snapshot = project_git_upstream.configure(
        root, remote="origin", branch="main",
    )
    _git(root, "config", key, concurrent_value)

    with pytest.raises(ProjectOnboardError, match="manual repair"):
        project_git_upstream.restore(root, snapshot)

    assert _git(root, "config", key) == concurrent_value
