"""A finished lane is kept only for work git reports; ignored files never block.

These tests drive real git: a lane holding only ignored files — Yoke's own
rendered `.yoke/` state, build output, an arbitrary ignored file — is
disposable and leaves with the tree; a tracked change or an untracked,
non-ignored file keeps it.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from yoke_core.engines.merge_landed_lane_cleanup import prune_landed_lane
from yoke_core.engines.merge_worktree_cleanliness import assess_lane_residue


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout


def _run_git(command, *, cwd=None, capture=True):
    return subprocess.run(
        ["git", *command], cwd=cwd, capture_output=True, text=True, check=False
    )


@pytest.fixture
def lane(tmp_path: Path) -> tuple[Path, Path]:
    """A repository ignoring build and Yoke output, with one landed lane."""
    repo = tmp_path / "repo"
    subprocess.run(
        ["git", "init", "--initial-branch=main", str(repo)],
        check=True,
        capture_output=True,
    )
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / ".gitignore").write_text(
        ".yoke/docs/\n.yoke/harness/\nout/\ndeploy/secrets/\n.venv/\n", encoding="utf-8"
    )
    (repo / "a.txt").write_text("a\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "base")
    path = repo / ".worktrees" / "YOK-1"
    _git(repo, "worktree", "add", "-b", "YOK-1", str(path), "main")
    return repo, path


def _fill_ignored(path: Path) -> None:
    for relative in (
        ".yoke/docs/agents/rules.md",
        ".yoke/harness/claude/hooks.json",
        "out/film/frame.png",
        "deploy/secrets/token",
    ):
        target = path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("generated\n", encoding="utf-8")


def _prune(repo: Path) -> tuple[str, ...]:
    return prune_landed_lane(
        repo_root=str(repo),
        branch="YOK-1",
        target="main",
        run_git=_run_git,
        emit=lambda *_a, **_kw: None,
    )


def test_a_lane_holding_only_ignored_files_is_removed(lane):
    repo, path = lane
    _fill_ignored(path)

    residue = assess_lane_residue(_run_git, path)
    assert residue.disposable, residue.reason

    assert _prune(repo) == ()
    assert not path.exists()
    assert _git(repo, "branch", "--list", "YOK-1").strip() == ""


def test_an_untracked_non_ignored_file_keeps_the_lane(lane):
    repo, path = lane
    _fill_ignored(path)
    (path / "notes.txt").write_text("keep\n", encoding="utf-8")

    residue = assess_lane_residue(_run_git, path)
    assert not residue.disposable
    assert residue.precious_paths == ("notes.txt",)

    preserved = _prune(repo)
    assert preserved and "notes.txt" in preserved[0]
    assert (path / "notes.txt").read_text(encoding="utf-8") == "keep\n"


def test_a_tracked_change_keeps_the_lane(lane):
    repo, path = lane
    (path / "a.txt").write_text("edited\n", encoding="utf-8")

    residue = assess_lane_residue(_run_git, path)
    assert not residue.disposable
    assert "unignored changes present: a.txt" in residue.reason

    assert _prune(repo)
    assert path.is_dir()


def test_status_never_asks_git_for_ignored_files(tmp_path: Path):
    seen: list[list[str]] = []

    def run_git(command, *, cwd=None, capture=True):
        seen.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    assert assess_lane_residue(run_git, tmp_path).disposable
    assert not any(arg.startswith("--ignored") for arg in seen[0])


def test_an_unreadable_status_keeps_the_lane(tmp_path: Path):
    def run_git(command, *, cwd=None, capture=True):
        return subprocess.CompletedProcess(command, 128, "", "fatal")

    residue = assess_lane_residue(run_git, tmp_path)
    assert not residue.disposable
    assert residue.reason == "worktree status unreadable"


def test_a_lane_holding_the_running_interpreter_is_kept(lane, monkeypatch):
    _repo, path = lane
    interpreter = path / ".venv" / "bin" / "python"
    interpreter.parent.mkdir(parents=True)
    interpreter.write_text("", encoding="utf-8")
    monkeypatch.setattr(sys, "executable", str(interpreter))

    residue = assess_lane_residue(_run_git, path)
    assert not residue.disposable
    assert residue.reason == "the lane contains the active interpreter"
