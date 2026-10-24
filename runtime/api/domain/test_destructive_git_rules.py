"""Shared destructive-git rules: both guards judge the same paths the same way."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest import mock

import pytest

from yoke_contracts.hook_runner import destructive_git_rules as rules
from yoke_core.domain import lint_destructive_git as ldg
from yoke_harness.hooks import local_policies
from yoke_harness.hooks.local_policy_common import DENY, NOOP


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=False
    )


def _commit_all(repo: Path, message: str) -> None:
    _git(repo, "add", "-A")
    assert _git(repo, "commit", "-q", "-m", message).returncode == 0


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "test")
    for name in ("catalog.txt", "other.txt", "sub/deep.txt"):
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(f"{name} v1\n")
    _commit_all(root, "seed")
    return root


def _core(command: str, cwd: Path) -> str | None:
    payload = {"tool_name": "Bash", "cwd": str(cwd), "tool_input": {"command": command}}
    with (
        mock.patch.object(ldg, "_claimed_worktree_threats", return_value=[]),
    ):
        verdict = ldg.evaluate_payload(payload)
    return verdict[0] if verdict else None


def _local(command: str, cwd: Path) -> str | None:
    payload = {"tool_name": "Bash", "cwd": str(cwd), "tool_input": {"command": command}}
    result = local_policies.lint_destructive_git(payload)
    if result.outcome == NOOP:
        return None
    assert result.outcome == DENY
    return result.message


GUARDS = pytest.mark.parametrize("guard", [_core, _local], ids=["core", "local"])


def _risk_lines(reason: str) -> list[str]:
    block = reason.split("Files at risk:\n", 1)[1].split("\n\n", 1)[0]
    return [line.strip() for line in block.splitlines()]


def _dirty_everything(repo: Path) -> None:
    for name in ("catalog.txt", "other.txt", "sub/deep.txt"):
        (repo / name).write_text(f"{name} edited\n")
    _git(repo, "add", "other.txt")


def _mid_rebase_conflict(repo: Path) -> None:
    _git(repo, "checkout", "-q", "-b", "topic")
    (repo / "catalog.txt").write_text("topic side\n")
    _commit_all(repo, "topic")
    _git(repo, "checkout", "-q", "main")
    (repo / "catalog.txt").write_text("main side\n")
    _commit_all(repo, "main")
    _git(repo, "checkout", "-q", "topic")
    assert _git(repo, "rebase", "main").returncode != 0
    assert _git(repo, "status", "--porcelain").stdout.startswith("UU catalog.txt")


@pytest.mark.parametrize(
    ("args", "shape"),
    [
        (["reset", "--hard"], "reset_hard"),
        (["reset", "--soft", "HEAD~1"], None),
        (["reset", "HEAD"], None),
        (["clean", "-f"], "clean_force"),
        (["clean", "-fd"], "clean_force"),
        (["clean", "-fdx"], "clean_force"),
        (["clean", "--force"], "clean_force"),
        (["clean", "-n"], None),
        (["clean", "-nf"], None),
        (["stash", "drop"], "stash_drop"),
        (["stash", "clear"], "stash_clear"),
        (["stash"], None),
        (["stash", "push", "-u"], None),
        (["stash", "list"], None),
        (["stash", "pop"], None),
        (["checkout", "--", "foo.txt"], "checkout_path_discard"),
        (["checkout", "-f", "main"], "checkout_force_branch"),
        (["checkout", "main"], None),
        (["checkout", "."], "checkout_path_discard"),
        (["checkout", "HEAD", "."], "checkout_path_discard"),
        (["checkout", "./sub/"], "checkout_path_discard"),
        (["restore", "--worktree", "foo.txt"], "restore_worktree_path"),
        (["restore", "foo.txt"], "restore_worktree_path"),
        (["restore", "--staged", "foo.txt"], None),
        (["restore", "-S", "foo.txt"], None),
        (["restore", "-S", "-W", "foo.txt"], "restore_worktree_path"),
        (["worktree", "remove", ".worktrees/a"], "worktree_remove"),
    ],
)
def test_classify_shape(args: list[str], shape: str | None) -> None:
    assert rules.classify_shape(args) == shape


def test_staged_short_flag_takes_no_value() -> None:
    assert rules.path_args(["restore", "-S", "a.txt"]) == ["a.txt"]


def test_source_flags_consume_value() -> None:
    assert rules.path_args(["restore", "-s", "HEAD~1", "a.txt"]) == ["a.txt"]
    assert rules.path_args(["restore", "--source", "HEAD~1", "a.txt"]) == ["a.txt"]


@GUARDS
def test_pathspec_limited_restore_lists_only_covered_paths(guard, repo: Path) -> None:
    _dirty_everything(repo)
    reason = guard("git restore --source=HEAD --staged --worktree -- sub", repo)
    assert reason is not None
    assert _risk_lines(reason) == ["sub/deep.txt"]


@GUARDS
def test_restore_staged_only_passes(guard, repo: Path) -> None:
    _dirty_everything(repo)
    assert guard("git restore --staged other.txt", repo) is None
    assert guard("git restore -S -- .", repo) is None


@GUARDS
def test_checkout_rev_path_lists_only_that_path(guard, repo: Path) -> None:
    _dirty_everything(repo)
    reason = guard("git checkout HEAD catalog.txt", repo)
    assert reason is not None
    assert _risk_lines(reason) == ["catalog.txt"]


@GUARDS
def test_restore_of_unmodified_path_passes(guard, repo: Path) -> None:
    (repo / "other.txt").write_text("edited\n")
    assert guard("git restore --worktree catalog.txt", repo) is None


@GUARDS
def test_mid_rebase_restore_of_conflicted_file_passes(guard, repo: Path) -> None:
    _mid_rebase_conflict(repo)
    (repo / "other.txt").write_text("hand edit\n")
    command = "git restore --source=main --staged --worktree -- catalog.txt"
    assert guard(command, repo) is None


@GUARDS
def test_mid_rebase_whole_tree_restore_still_denied(guard, repo: Path) -> None:
    _mid_rebase_conflict(repo)
    (repo / "other.txt").write_text("hand edit\n")
    reason = guard("git restore --worktree .", repo)
    assert reason is not None
    assert _risk_lines(reason) == ["other.txt"]


@GUARDS
def test_whole_tree_restore_is_denied(guard, repo: Path) -> None:
    _dirty_everything(repo)
    reason = guard("git restore --worktree .", repo)
    assert reason is not None
    assert sorted(_risk_lines(reason)) == ["catalog.txt", "other.txt", "sub/deep.txt"]


def test_unmerged_paths_count_outside_a_conflict_operation(repo: Path) -> None:
    porcelain = subprocess.CompletedProcess([], 0, stdout="UU catalog.txt\n", stderr="")
    probe = subprocess.CompletedProcess([], 0, stdout=".git/rebase-merge\n", stderr="")

    def run_git(_worktree: str, *args: str):
        return porcelain if args[0] == "status" else probe

    assert rules.worktree_status(str(repo), run_git) == (["catalog.txt"], [])


def test_both_guards_render_the_same_refusal(repo: Path) -> None:
    _dirty_everything(repo)
    core = _core("git reset --hard", repo)
    local = _local("git reset --hard", repo)
    assert core is not None and local is not None
    assert local.split("Doctrine:")[0] == core.split("Doctrine:")[0]
