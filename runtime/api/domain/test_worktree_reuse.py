"""Corrupt leftover lanes are repaired or refused before reuse."""

from __future__ import annotations

import subprocess
from pathlib import Path

from yoke_core.domain.worktree import create_worktree
from yoke_core.domain.worktree_create_plan import WorktreeCreationEntry
from yoke_core.domain.worktree_provision import (
    GIT_WORKTREE_ADD_TIMEOUT_SECONDS,
    provision_worktree,
)
from yoke_core.domain.worktree_reuse import classify_reusable_worktree


def _git(cwd: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", cwd, *args],
        check=True,
        capture_output=True,
        text=True,
    )


def test_null_recorded_path_is_refused() -> None:
    preexisting, err = classify_reusable_worktree("YOK-1", "")
    assert preexisting is False
    assert err == "recorded worktree path is null"


def test_non_worktree_directory_is_refused(tmp_path: Path) -> None:
    leftover = tmp_path / "YOK-1"
    leftover.mkdir()
    preexisting, err = classify_reusable_worktree("YOK-1", str(leftover))
    assert preexisting is False
    assert err is not None
    assert "not a git worktree" in err


def test_healthy_worktree_is_preexisting(git_repo: Path, yoke_db: str) -> None:
    first = create_worktree(
        24121,
        repo_root=str(git_repo),
        config_path=str(git_repo / "runtime" / "config"),
    )
    assert first.error is None
    preexisting, err = classify_reusable_worktree(first.branch, first.path)
    assert err is None
    assert preexisting is True


def test_empty_index_and_missing_files_are_repaired_on_reuse(
    git_repo: Path,
    yoke_db: str,
) -> None:
    first = create_worktree(
        24122,
        repo_root=str(git_repo),
        config_path=str(git_repo / "runtime" / "config"),
    )
    assert first.error is None
    wt = first.path
    _git(wt, "read-tree", "--empty")
    Path(wt, "README.md").unlink()
    listed = subprocess.run(
        ["git", "-C", wt, "ls-files"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert listed.stdout.strip() == ""

    second = create_worktree(
        24122,
        repo_root=str(git_repo),
        config_path=str(git_repo / "runtime" / "config"),
    )
    assert second.error is None
    assert second.created is False
    indexed = _git(wt, "ls-files")
    assert "README.md" in indexed.stdout
    assert Path(wt, "README.md").is_file()


def test_git_worktree_add_failure_keeps_stderr(monkeypatch, tmp_path: Path) -> None:
    seen_timeout: list[int] = []

    def fake_run(cmd, cwd=None, timeout=30):
        if "worktree" in cmd and "add" in cmd:
            seen_timeout.append(timeout)
            return subprocess.CompletedProcess(
                cmd,
                1,
                stdout="",
                stderr="fatal: already used by worktree\n",
            )
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(
        "yoke_core.domain.worktree_provision._run",
        fake_run,
    )
    entry = WorktreeCreationEntry(
        branch="YOK-2412",
        path=str(tmp_path / "lane"),
    )
    err = provision_worktree(
        entry,
        str(tmp_path),
        "main",
        "yoke",
        str(tmp_path),
    )
    assert err is not None
    assert "fatal: already used by worktree" in err
    assert seen_timeout == [GIT_WORKTREE_ADD_TIMEOUT_SECONDS]


def test_git_worktree_add_empty_output_is_visible(monkeypatch, tmp_path: Path) -> None:
    def fake_run(cmd, cwd=None, timeout=30):
        if "worktree" in cmd and "add" in cmd:
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(
        "yoke_core.domain.worktree_provision._run",
        fake_run,
    )
    entry = WorktreeCreationEntry(
        branch="YOK-2412",
        path=str(tmp_path / "lane"),
    )
    err = provision_worktree(
        entry,
        str(tmp_path),
        "main",
        "yoke",
        str(tmp_path),
    )
    assert err is not None
    assert "(no git output)" in err
    assert err.startswith("git worktree add failed")
