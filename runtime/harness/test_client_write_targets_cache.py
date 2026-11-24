"""Write-target facts reuse repository answers only while Git state is unchanged."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from yoke_contracts.hook_runner.bash_paths import canonical_native_path
from yoke_harness.hooks import client_write_targets as targets


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git("init", "-q", cwd=repo)
    _git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q",
         "--allow-empty", "-m", "init", cwd=repo)
    return repo


def test_a_new_or_removed_lane_is_seen_on_the_next_hook(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    lane = tmp_path / "lane"
    assert canonical_native_path(str(lane)) not in targets._worktrees(str(repo))

    _git("worktree", "add", "-q", str(lane), cwd=repo)
    assert canonical_native_path(str(lane)) in targets._worktrees(str(repo))

    _git("worktree", "remove", str(lane), cwd=repo)
    assert canonical_native_path(str(lane)) not in targets._worktrees(str(repo))


def test_unchanged_repository_answers_spawn_no_git(tmp_path: Path, monkeypatch) -> None:
    repo = _repo(tmp_path)
    _git("worktree", "add", "-q", str(tmp_path / "lane"), cwd=repo)
    calls = []
    real = targets._git

    def counted(*args, **kwargs):
        calls.append(args[1][0])
        return real(*args, **kwargs)

    monkeypatch.setattr(targets, "_git", counted)
    first = targets._worktrees(str(repo))
    targets._ignored(str(repo), [os.path.join(str(repo), "a.txt")])
    spawned = list(calls)
    calls.clear()

    assert targets._worktrees(str(repo)) == first
    targets._ignored(str(repo), [os.path.join(str(repo), "a.txt")])
    assert "worktree" in spawned and "rev-parse" in spawned
    assert calls == ["check-ignore"]


def test_routine_git_writes_inside_a_lane_keep_the_listing(tmp_path: Path, monkeypatch) -> None:
    """Index and lock writes touch the entry folder, not the lane set."""
    repo = _repo(tmp_path)
    lane = tmp_path / "lane"
    _git("worktree", "add", "-q", str(lane), cwd=repo)
    targets._worktrees(str(repo))
    entry = next((repo / ".git" / "worktrees").iterdir())
    (entry / "index.lock").write_text("")
    (entry / "index.lock").unlink()
    os.utime(entry, (1, 1))
    calls = []
    real = targets._git
    monkeypatch.setattr(
        targets, "_git", lambda *a, **k: calls.append(a[1][0]) or real(*a, **k)
    )

    assert canonical_native_path(str(lane)) in targets._worktrees(str(repo))
    assert calls == []


def test_a_moved_lane_is_seen_on_the_next_hook(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    lane, moved = tmp_path / "lane", tmp_path / "moved"
    _git("worktree", "add", "-q", str(lane), cwd=repo)
    assert canonical_native_path(str(lane)) in targets._worktrees(str(repo))

    _git("worktree", "move", str(lane), str(moved), cwd=repo)
    listed = targets._worktrees(str(repo))
    assert canonical_native_path(str(moved)) in listed
    assert canonical_native_path(str(lane)) not in listed
