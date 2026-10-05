"""Local Git fixtures shared by project publishing tests."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from yoke_cli.config import project_publish_support as pub


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _init_repo(root: Path, branch: str = "main") -> None:
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "--initial-branch", branch)
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "Test")


@pytest.fixture(autouse=True)
def _local_git_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        pub,
        "run_git",
        lambda root, *args, **_kwargs: _git(root, *args),
    )
