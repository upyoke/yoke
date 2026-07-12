from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from yoke_cli.config import project_local_git
from yoke_cli.config.project_onboard_support import ProjectOnboardError


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args], cwd=root, check=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )


def test_current_branch_accepts_unborn_attached_branch(tmp_path: Path) -> None:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    _git(checkout, "init", "--initial-branch", "trunk")

    assert project_local_git.current_branch(checkout) == "trunk"


def test_current_branch_rejects_detached_head(tmp_path: Path) -> None:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    _git(checkout, "init", "--initial-branch", "main")
    _git(checkout, "config", "user.email", "test@example.com")
    _git(checkout, "config", "user.name", "Test")
    (checkout / "README.md").write_text("# checkout\n", encoding="utf-8")
    _git(checkout, "add", "README.md")
    _git(checkout, "commit", "-m", "Initial commit")
    _git(checkout, "checkout", "--detach")

    with pytest.raises(ProjectOnboardError, match="current git branch"):
        project_local_git.current_branch(checkout)
