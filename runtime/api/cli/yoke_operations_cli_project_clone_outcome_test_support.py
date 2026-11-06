# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import subprocess

from pathlib import Path

import pytest

from yoke_cli.config import github_publish

from yoke_cli.config import project_clone_support as clone

from yoke_cli.config import project_onboard

from yoke_cli.config import project_onboard_clone

from yoke_cli.config.project_publish_support import PublishRequest


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    return result.stdout.strip()


def _seed_bare_source(tmp_path: Path, name: str, *, branch: str = "main") -> Path:
    work = tmp_path / f"{name}-work"
    work.mkdir()
    _git(work, "init", "--initial-branch", branch)
    _git(work, "config", "user.email", "t@example.com")
    _git(work, "config", "user.name", "Test")
    (work / "README.md").write_text("# source\n", encoding="utf-8")
    _git(work, "add", "README.md")
    _git(work, "commit", "-m", "seed")
    bare = tmp_path / f"{name}.git"
    _git(tmp_path, "clone", "--bare", str(work), str(bare))
    return bare


def _clone_into(tmp_path: Path, bare: Path, name: str) -> Path:
    parent = tmp_path / "checkouts"
    parent.mkdir(exist_ok=True)
    _git(parent, "clone", str(bare), name)
    target = parent / name
    _git(target, "config", "user.email", "t@example.com")
    _git(target, "config", "user.name", "Test")
    return target
