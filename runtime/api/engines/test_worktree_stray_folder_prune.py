"""Judging unregistered managed folders by the main checkout's ignore rules."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from yoke_core.engines.worktree_stray_folder_prune import (
    assess_stray_folders,
    first_unignored_path,
    prune_stray_folders,
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _run_git(command, *, cwd=None, capture=True):
    return subprocess.run(
        ["git", *command], cwd=cwd, capture_output=True, text=True, check=False
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    subprocess.run(
        ["git", "init", "-q", "--initial-branch=main", str(root)], check=True
    )
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")
    (root / ".gitignore").write_text("node_modules/\n.next/\n*.log\n", encoding="utf-8")
    _git(root, "add", ".gitignore")
    _git(root, "commit", "-q", "-m", "base")
    return root


def _write(path: Path, text: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_only_ignored_paths_have_no_first_unignored(repo: Path):
    folder = repo / ".worktrees" / "stray"
    _write(folder / "node_modules" / "pkg" / "index.js")
    _write(folder / "app" / ".next" / "build")
    _write(folder / "run.log")
    _write(folder / ".git", "gitdir: /nowhere\n")

    assert first_unignored_path(repo, folder) == ""


def test_a_non_ignored_file_is_named(repo: Path):
    folder = repo / ".worktrees" / "stray"
    _write(folder / "node_modules" / "pkg" / "index.js")
    _write(folder / "app" / "page.tsx")

    assert first_unignored_path(repo, folder) == "app/page.tsx"


def test_a_directory_pattern_does_not_ignore_a_same_named_file(repo: Path):
    folder = repo / ".worktrees" / "stray"
    _write(folder / "node_modules")

    assert first_unignored_path(repo, folder) == "node_modules"


def test_registered_lanes_tombstones_and_empty_folders_are_not_strays(repo: Path):
    lane = repo / ".worktrees" / "YOK-1"
    _git(repo, "worktree", "add", "-q", "-b", "YOK-1", str(lane), "main")
    (repo / ".worktrees" / ".removing-old-1234").mkdir()
    _write(repo / ".worktrees" / ".removing-old-1234" / "run.log")
    (repo / ".worktrees" / "empty").mkdir()
    _write(repo / ".claude" / "worktrees" / "agent" / ".next" / "x")

    found = assess_stray_folders(repo, _run_git)

    assert found is not None
    assert [stray.path.name for stray in found] == ["agent"]


def test_prune_removes_only_disposable_strays(repo: Path):
    disposable = repo / ".worktrees" / "gone"
    kept = repo / ".worktrees" / "kept"
    _write(disposable / ".next" / "x")
    _write(kept / "notes.md")

    results = {stray.path.name: stray for stray in prune_stray_folders(repo, _run_git)}

    assert results["gone"].removed and not disposable.exists()
    assert not results["kept"].removed and kept.is_dir()
    assert results["kept"].first_unignored == "notes.md"
    assert not any(
        p.name.startswith(".removing-") for p in (repo / ".worktrees").iterdir()
    )
