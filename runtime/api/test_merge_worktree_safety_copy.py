"""Safety copies preserve lane files independently of the shared stash list."""

import subprocess
from types import SimpleNamespace

import pytest

from yoke_core.engines import merge_worktree
from yoke_core.engines.merge_worktree_prepare_state import _stash_classify_gate


def git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True, text=True, check=False,
    )


@pytest.fixture
def lanes(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    assert git(repo, "init").returncode == 0
    assert git(repo, "config", "user.email", "test@example.com").returncode == 0
    assert git(repo, "config", "user.name", "Test").returncode == 0
    (repo / "code.txt").write_text("base\n")
    assert git(repo, "add", ".").returncode == 0
    assert git(repo, "commit", "-m", "base").returncode == 0
    lane = tmp_path / "lane"
    assert git(repo, "worktree", "add", "-b", "lane", str(lane)).returncode == 0
    (repo / "code.txt").write_text("other lane\n")
    assert git(repo, "stash", "push", "-m", "other-lane").returncode == 0
    other_sha = git(repo, "rev-parse", "refs/stash").stdout.strip()
    messages = []
    monkeypatch.setattr(merge_worktree, "_print", lambda text, **kw: messages.append(text))

    def run_git(args, cwd, capture=True):
        return git(cwd, *args)

    monkeypatch.setattr(merge_worktree, "_run_git", run_git)
    ctx = SimpleNamespace(worktree_path=str(lane), args=SimpleNamespace(branch="lane"))
    return repo, lane, ctx, other_sha, messages, run_git


@pytest.mark.parametrize("staged", [False, True])
def test_safety_copy_preserves_dirty_lane_and_other_stash(lanes, staged):
    repo, lane, ctx, other_sha, messages, _ = lanes
    (lane / "code.txt").write_text("this lane\n")
    if staged:
        assert git(lane, "add", "code.txt").returncode == 0
    (lane / "untracked.txt").write_text("untracked\n")
    before = git(lane, "status", "--porcelain").stdout
    index = git(lane, "diff", "--cached").stdout
    result = _stash_classify_gate(ctx)
    assert result[0] == 4
    assert (lane / "code.txt").read_text() == "this lane\n"
    assert (lane / "untracked.txt").read_text() == "untracked\n"
    assert git(lane, "status", "--porcelain").stdout == before
    assert git(lane, "diff", "--cached").stdout == index
    safety_sha = git(repo, "rev-parse", "refs/stash").stdout.strip()
    assert safety_sha != other_sha
    assert git(repo, "show", f"{safety_sha}:code.txt").stdout == "this lane\n"
    assert git(repo, "stash", "list", "--format=%H").stdout.splitlines() == [
        safety_sha, other_sha,
    ]
    assert any(f"git stash apply {safety_sha}" in message for message in messages)
    assert not any("stash@{0}" in message for message in messages)


def test_untracked_only_does_not_apply_or_replace_other_stash(lanes):
    repo, lane, ctx, other_sha, messages, _ = lanes
    (lane / "untracked.txt").write_text("untracked\n")
    assert _stash_classify_gate(ctx)[0] == 4
    assert (lane / "code.txt").read_text() == "base\n"
    assert (lane / "untracked.txt").read_text() == "untracked\n"
    assert git(repo, "rev-parse", "refs/stash").stdout.strip() == other_sha
    assert not any("safe in stash" in message for message in messages)


@pytest.mark.parametrize("operation", ["status", "create", "store", "diff", "ls-files"])
def test_failed_safety_copy_refuses_without_changing_files(lanes, monkeypatch, operation):
    repo, lane, ctx, other_sha, messages, run_git = lanes
    (lane / "code.txt").write_text("this lane\n")
    (lane / "untracked.txt").write_text("untracked\n")
    before = git(lane, "status", "--porcelain").stdout

    def fail(args, cwd, capture=True):
        if operation in args:
            return subprocess.CompletedProcess(args, 1, "", "injected git failure")
        return run_git(args, cwd, capture)

    monkeypatch.setattr(merge_worktree, "_run_git", fail)
    result = _stash_classify_gate(ctx)
    assert result[0] == 4
    assert "merge_safety_copy_failed" in result[1]
    assert "Commit the lane's work" in result[1]
    assert "injected git failure" in result[1]
    assert git(lane, "status", "--porcelain").stdout == before
    assert (lane / "code.txt").read_text() == "this lane\n"
    assert (lane / "untracked.txt").read_text() == "untracked\n"
    assert other_sha in git(repo, "stash", "list", "--format=%H").stdout


def test_concurrent_stash_does_not_change_the_copied_commit(lanes, monkeypatch):
    repo, lane, ctx, other_sha, messages, run_git = lanes
    (lane / "code.txt").write_text("this lane\n")
    concurrent_sha = None

    def interleave(args, cwd, capture=True):
        nonlocal concurrent_sha
        result = run_git(args, cwd, capture)
        if args == ["stash", "create"]:
            (repo / "code.txt").write_text("concurrent work\n")
            assert git(repo, "stash", "push", "-m", "concurrent").returncode == 0
            concurrent_sha = git(repo, "rev-parse", "refs/stash").stdout.strip()
        return result

    monkeypatch.setattr(merge_worktree, "_run_git", interleave)
    assert _stash_classify_gate(ctx)[0] == 4
    safety_sha = git(repo, "rev-parse", "refs/stash").stdout.strip()
    assert git(repo, "show", f"{safety_sha}:code.txt").stdout == "this lane\n"
    assert (lane / "code.txt").read_text() == "this lane\n"
    assert git(repo, "stash", "list", "--format=%H").stdout.splitlines() == [
        safety_sha, concurrent_sha, other_sha,
    ]
    assert any(safety_sha in message for message in messages)
