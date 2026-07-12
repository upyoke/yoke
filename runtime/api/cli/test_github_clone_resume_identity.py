"""Clone resume requires the exact target worktree under a sanitized boundary."""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from yoke_cli.config import project_clone_resume
from yoke_cli.config.project_git_process import NetworkGitBoundaryError


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=root, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
    )
    return result.stdout.strip()


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "source"
    root.mkdir()
    _git(root, "init", "--initial-branch", "main")
    _git(
        root, "remote", "add", "origin",
        "https://github.com/acme/widgets.git",
    )
    return root


def test_nested_directory_is_not_a_resumable_clone(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    nested = root / "nested"
    nested.mkdir()

    assert project_clone_resume.existing_clone_matches(
        root, "https://github.com/acme/widgets.git",
    ) is True
    assert project_clone_resume.existing_clone_matches(
        nested, "https://github.com/acme/widgets.git",
    ) is False


def test_ambient_git_routing_cannot_spoof_resume_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _repo(tmp_path)
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    monkeypatch.setenv("GIT_DIR", str(source / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(source))
    monkeypatch.setenv("GIT_CONFIG", str(source / ".git" / "config"))

    assert project_clone_resume.existing_clone_matches(
        unrelated, "https://github.com/acme/widgets.git",
    ) is False


def test_resume_probe_fails_closed_on_process_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _repo(tmp_path)
    monkeypatch.setattr(
        project_clone_resume.project_local_git,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            NetworkGitBoundaryError("deadline")
        ),
    )

    assert project_clone_resume.existing_clone_matches(
        root, "https://github.com/acme/widgets.git",
    ) is False


def test_enterprise_ssh_and_https_represent_the_same_repository() -> None:
    assert project_clone_resume.same_repo(
        "git@ghe.example:acme/widgets.git",
        "https://ghe.example/acme/widgets.git",
    ) is True
    assert project_clone_resume.same_repo(
        "git@ghe.example:acme/widgets.git",
        "https://other.example/acme/widgets.git",
    ) is False


def test_configured_enterprise_origin_rejects_cross_host_identity() -> None:
    assert project_clone_resume.same_repo(
        "git@ghe.example:acme/widgets.git",
        "https://ghe.example/acme/widgets.git",
        web_url="https://ghe.example",
    ) is True
    assert project_clone_resume.same_repo(
        "git@other.example:acme/widgets.git",
        "https://ghe.example/acme/widgets.git",
        web_url="https://ghe.example",
    ) is False
