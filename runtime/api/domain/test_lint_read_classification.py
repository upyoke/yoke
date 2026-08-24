"""Read-classification false-positive shapes for lane and fleet guards."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

from runtime.api.domain.lint_session_cwd_test_helpers import (
    seed_item,
    seed_item_claim,
)
from runtime.api.fixtures.machine_config_test import register_machine_checkout
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain import lint_lane_main_write, lint_session_cwd
from yoke_core.domain.lint_lane_main_write_classify import is_write_operation
from yoke_core.domain.lint_session_cwd_read_only_signatures import (
    match_read_only_signature,
)
from yoke_core.domain.lint_session_cwd_target_extract import (
    extract_payload_write_targets,
)


SESSION = "sid-lane"
ITEM_ID = 2386


def _seed_lane(conn, repo):
    register_machine_checkout(
        Path(repo).parent / "machine-config", Path(repo), project_id=1,
    )
    seed_item(
        conn, item_id=ITEM_ID, branch=f"YOK-{ITEM_ID}",
        status="implementing", repo_path=repo,
    )
    seed_item_claim(conn, SESSION, item_id=ITEM_ID)
    lane = repo / ".worktrees" / f"YOK-{ITEM_ID}"
    lane.mkdir(parents=True, exist_ok=True)
    return lane


def _bash(command, *, cwd, workdir=None):
    tool_input = {"command": command}
    if workdir is not None:
        tool_input["workdir"] = workdir
    return {
        "session_id": SESSION,
        "tool_name": "Bash",
        "cwd": cwd,
        "tool_input": tool_input,
    }


def test_compound_git_log_on_main_is_not_a_write():
    command = "yoke relay status 2>&1; git -C /Users/beebauman/yoke log --oneline -1"
    assert match_read_only_signature(command) == "compound-read"
    assert is_write_operation("Bash", {"tool_input": {"command": command}}) is False
    assert extract_payload_write_targets({"tool_input": {"command": command}}) == []


def test_rg_without_destination_is_not_a_write():
    command = "rg lint_lane_main_write packages"
    assert match_read_only_signature(command) == "rg"
    assert is_write_operation("Bash", {"tool_input": {"command": command}}) is False
    assert extract_payload_write_targets({"tool_input": {"command": command}}) == []


def test_compound_git_log_allows_with_lane_claim(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".worktrees").mkdir(parents=True)
    command = f"yoke relay status 2>&1; git -C {repo} log --oneline -1"
    with test_database() as conn:
        _seed_lane(conn, repo)
        verdict = lint_lane_main_write.evaluate_pre_tool_use(_bash(
            command, cwd=str(repo),
        ))
    assert verdict.allow is True


def test_rg_does_not_fallback_cwd_as_main_write(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".worktrees").mkdir(parents=True)
    with test_database() as conn:
        _seed_lane(conn, repo)
        verdict = lint_lane_main_write.evaluate_pre_tool_use(_bash(
            "rg pattern", cwd=str(repo),
        ))
    assert verdict.allow is True


def test_deployment_flow_inspection_allows_with_lane_claim(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".worktrees").mkdir(parents=True)
    command = "yoke deployment-flows get platform-prod-hotfix-hosted"
    with test_database() as conn:
        _seed_lane(conn, repo)
        main_verdict = lint_lane_main_write.evaluate_pre_tool_use(_bash(
            command, cwd=str(repo),
        ))
        cwd_verdict = lint_session_cwd.evaluate_pre_tool_use(_bash(
            command, cwd=str(repo),
        ))
    assert main_verdict.allow is True
    assert cwd_verdict.allow is True


def test_git_commit_on_main_still_denies(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".worktrees").mkdir(parents=True)
    with test_database() as conn:
        _seed_lane(conn, repo)
        with mock.patch.object(lint_lane_main_write, "emit_denied", return_value=None):
            verdict = lint_lane_main_write.evaluate_pre_tool_use(_bash(
                f"git -C {repo} commit -m slice", cwd=str(repo),
            ))
    assert verdict.allow is False
    assert str(repo.resolve()) in verdict.reason
