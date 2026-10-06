"""Reads of a lane that is still at idea are not worktree writes.

A cat of lane docs at idea was refused as a worktree write, and
``python -m playwright`` against the lane module path was treated the
same way. The write-target resolver does not call either a write.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.api.domain.lint_session_cwd_test_helpers import (
    seed_item,
    seed_item_claim,
)
from runtime.api.fixtures.machine_config_test import register_machine_checkout
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain import lint_session_cwd


HOLDER = "sid-holder"
HELD_ITEM = 2220


@pytest.fixture
def conn():
    with test_database() as c:
        yield c


@pytest.fixture
def repo(tmp_path):
    repo_path = tmp_path / "repo"
    (repo_path / ".worktrees").mkdir(parents=True)
    return repo_path


def _idea_lane(conn, repo, *, workflow_id="dash"):
    register_machine_checkout(Path(repo).parent / "machine-config", Path(repo), 1)
    seed_item(
        conn,
        item_id=HELD_ITEM,
        branch=f"YOK-{HELD_ITEM}",
        repo_path=repo,
        status="idea",
        workflow_id=workflow_id,
    )
    seed_item_claim(conn, HOLDER, HELD_ITEM)
    lane = repo / ".worktrees" / f"YOK-{HELD_ITEM}"
    lane.mkdir(parents=True, exist_ok=True)
    return lane


def _bash(lane, command):
    return lint_session_cwd.evaluate_pre_tool_use(
        {
            "session_id": HOLDER,
            "cwd": str(lane),
            "tool_name": "Bash",
            "tool_input": {"command": command},
        }
    )


def test_two_file_cat_at_idea_is_allowed(conn, repo):
    lane = _idea_lane(conn, repo)
    verdict = _bash(lane, f"cat {lane}/README.md {lane}/NOTES.md")
    assert verdict.allow is True


def test_playwright_module_path_at_idea_is_allowed(conn, repo):
    lane = _idea_lane(conn, repo)
    module = lane / ".venv/lib/python3.12/site-packages/playwright/__init__.py"
    assert _bash(lane, f"python3 {module}").allow is True
    assert _bash(lane, "python3 -m playwright --version").allow is True


def test_dash_write_denial_names_the_live_skill(conn, repo):
    lane = _idea_lane(conn, repo)
    verdict = lint_session_cwd.evaluate_pre_tool_use(
        {
            "session_id": HOLDER,
            "tool_name": "Write",
            "tool_input": {"file_path": str(lane / "src" / "a.py")},
        }
    )
    assert verdict.allow is False
    assert "/yoke dash " in verdict.reason
    assert "advance" not in verdict.reason
    assert "--to implementing" in verdict.reason
