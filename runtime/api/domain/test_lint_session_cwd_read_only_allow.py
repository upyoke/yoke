"""Integration test for the read-only / self-orientation allow branch.

A read-only db_router query invoked from a cwd
outside the session's claim allows (and emits the new allow event),
while a non-read-only command from the same cwd still denies.
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


@pytest.fixture
def conn():
    with test_database() as c:
        yield c


@pytest.fixture
def repo(tmp_path):
    repo_path = tmp_path / "repo"
    (repo_path / ".worktrees").mkdir(parents=True)
    return repo_path


def _seed_claimed_worktree(conn, repo):
    register_machine_checkout(
        Path(repo).parent / "machine-config",
        Path(repo),
        1,
    )
    seed_item(conn, item_id=1691, branch="YOK-1691", repo_path=repo)
    seed_item_claim(conn, "sid-1", item_id=1691)
    (repo / ".worktrees" / "YOK-1691").mkdir(parents=True)


# ---------------------------------------------------------------------------
# Read-only db_router query from outside-authority cwd allows
# ---------------------------------------------------------------------------


class TestReadOnlySignatureAllowsFromOutsideCwd:
    def test_db_router_query_allows_from_outside_authority(self, conn, repo):
        _seed_claimed_worktree(conn, repo)

        verdict = lint_session_cwd.evaluate_pre_tool_use({
            "session_id": "sid-1",
            "cwd": str(repo / ".worktrees/unclaimed"),
            "tool_input": {
                "command": (
                    'python3 -m yoke_core.cli.db_router '
                    'query "SELECT 1"'
                ),
            },
        })

        assert verdict.allow is True

    def test_who_claims_allows_from_outside_authority(self, conn, repo):
        _seed_claimed_worktree(conn, repo)

        verdict = lint_session_cwd.evaluate_pre_tool_use({
            "session_id": "sid-1",
            "cwd": str(repo / ".worktrees/unclaimed"),
            "tool_input": {
                "command": (
                    "python3 -m yoke_core.hooks.sessions_cli "
                    "who-claims YOK-1691"
                ),
            },
        })

        assert verdict.allow is True

    def test_git_status_allows_from_outside_authority(self, conn, repo):
        _seed_claimed_worktree(conn, repo)

        verdict = lint_session_cwd.evaluate_pre_tool_use({
            "session_id": "sid-1",
            "cwd": "/opt/elsewhere",
            "tool_input": {"command": "git status"},
        })

        assert verdict.allow is True


# ---------------------------------------------------------------------------
# The read-only branch emits the allow event, not the deny event
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# A non-read-only command from the same outside cwd still denies
# ---------------------------------------------------------------------------


class TestNonReadOnlyStillDenies:
    def test_mutating_command_from_outside_authority_denies(
        self, conn, repo,
    ):
        _seed_claimed_worktree(conn, repo)

        verdict = lint_session_cwd.evaluate_pre_tool_use({
            "session_id": "sid-1",
            "cwd": str(repo / ".worktrees/unclaimed"),
            "tool_input": {
                "command": (
                    "python3 -m yoke_core.engines.advance_implementation_entry "
                    "--item YOK-1691"
                ),
            },
        })

        assert verdict.allow is False

    def test_synthetic_outside_path_still_denies(self, conn, repo):
        # A write into an unclaimed governed lane still refuses.
        _seed_claimed_worktree(conn, repo)

        verdict = lint_session_cwd.evaluate_pre_tool_use({
            "session_id": "sid-1",
            "cwd": str(repo),
            "tool_input": {"command": f"touch {repo}/.worktrees/unclaimed/out.py"},
        })

        assert verdict.allow is False
        assert verdict.offending_target == str(repo / ".worktrees/unclaimed/out.py")
