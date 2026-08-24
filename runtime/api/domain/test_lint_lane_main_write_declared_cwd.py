"""Lane-main-write guard honors the call's declared workdir."""

from __future__ import annotations

from unittest import mock

from runtime.api.domain.lint_session_cwd_test_helpers import (
    seed_item,
    seed_item_claim,
)
from runtime.api.fixtures.machine_config_test import register_machine_checkout
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain import lint_lane_main_write


def _seed_lane(conn, repo, *, session_id="sid-lane", item_id=2013):
    register_machine_checkout(
        repo.parent / "machine-config", repo, project_id=1,
    )
    seed_item(
        conn, item_id=item_id, branch=f"YOK-{item_id}",
        status="implementing", repo_path=repo,
    )
    seed_item_claim(conn, session_id, item_id=item_id)
    worktree = repo / ".worktrees" / f"YOK-{item_id}"
    worktree.mkdir(parents=True, exist_ok=True)
    return worktree


def _bash(session_id, command, *, cwd, workdir=None):
    tool_input = {"command": command}
    if workdir is not None:
        tool_input["workdir"] = workdir
    return {
        "session_id": session_id,
        "tool_name": "Bash",
        "cwd": cwd,
        "tool_input": tool_input,
    }


def test_relative_touch_from_lane_workdir_allows(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".worktrees").mkdir(parents=True)
    with test_database() as conn:
        worktree = _seed_lane(conn, repo)
        verdict = lint_lane_main_write.evaluate_pre_tool_use(_bash(
            "sid-lane",
            "touch probe-guard-check.txt",
            cwd=str(repo),
            workdir=str(worktree),
        ))
    assert verdict.allow is True


def test_relative_touch_from_session_cwd_denies(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".worktrees").mkdir(parents=True)
    with test_database() as conn:
        worktree = _seed_lane(conn, repo)
        with mock.patch.object(lint_lane_main_write, "emit_denied", return_value=None):
            verdict = lint_lane_main_write.evaluate_pre_tool_use(_bash(
                "sid-lane",
                "touch probe-guard-check.txt",
                cwd=str(repo),
            ))
    assert verdict.allow is False
    assert str(repo / "probe-guard-check.txt") in verdict.reason
    assert str(worktree / "probe-guard-check.txt") in verdict.reason


def test_parent_traversal_to_worktrees_root_denies(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".worktrees").mkdir(parents=True)
    with test_database() as conn:
        worktree = _seed_lane(conn, repo)
        with mock.patch.object(lint_lane_main_write, "emit_denied", return_value=None):
            verdict = lint_lane_main_write.evaluate_pre_tool_use(_bash(
                "sid-lane",
                "touch ../probe.txt",
                cwd=str(repo),
                workdir=str(worktree),
            ))
    assert verdict.allow is False
    assert str((repo / ".worktrees" / "probe.txt").resolve()) in verdict.reason


def test_parent_traversal_to_main_denies(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".worktrees").mkdir(parents=True)
    with test_database() as conn:
        worktree = _seed_lane(conn, repo)
        with mock.patch.object(lint_lane_main_write, "emit_denied", return_value=None):
            verdict = lint_lane_main_write.evaluate_pre_tool_use(_bash(
                "sid-lane",
                "touch ../../probe.txt",
                cwd=str(repo),
                workdir=str(worktree),
            ))
    assert verdict.allow is False
    assert str((repo / "probe.txt").resolve()) in verdict.reason


def test_absolute_main_target_still_denies(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".worktrees").mkdir(parents=True)
    with test_database() as conn:
        worktree = _seed_lane(conn, repo)
        target = repo / "absolute-main.txt"
        with mock.patch.object(lint_lane_main_write, "emit_denied", return_value=None):
            verdict = lint_lane_main_write.evaluate_pre_tool_use(_bash(
                "sid-lane",
                f"touch {target}",
                cwd=str(repo),
                workdir=str(worktree),
            ))
    assert verdict.allow is False
    assert str(target.resolve()) in verdict.reason


def test_git_commit_from_lane_workdir_allows(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".worktrees").mkdir(parents=True)
    with test_database() as conn:
        worktree = _seed_lane(conn, repo)
        verdict = lint_lane_main_write.evaluate_pre_tool_use(_bash(
            "sid-lane",
            "git commit -m slice",
            cwd=str(repo),
            workdir=str(worktree),
        ))
    assert verdict.allow is True


def test_relative_git_commit_path_from_lane_workdir_allows(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".worktrees").mkdir(parents=True)
    with test_database() as conn:
        worktree = _seed_lane(conn, repo)
        verdict = lint_lane_main_write.evaluate_pre_tool_use(_bash(
            "sid-lane",
            "git commit -m slice -- packages/foo.py",
            cwd=str(repo),
            workdir=str(worktree),
        ))
    assert verdict.allow is True


def test_git_commit_on_main_without_workdir_denies(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".worktrees").mkdir(parents=True)
    with test_database() as conn:
        _seed_lane(conn, repo)
        with mock.patch.object(lint_lane_main_write, "emit_denied", return_value=None):
            verdict = lint_lane_main_write.evaluate_pre_tool_use(_bash(
                "sid-lane",
                "git commit -m slice",
                cwd=str(repo),
            ))
    assert verdict.allow is False
