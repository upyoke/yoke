"""Regression: shell-heredoc redirects to main are lane-main-write denials.

A ``cat > <relative path> <<PY`` write whose body contains an apostrophe
used to pass PreToolUse while the equivalent python-heredoc write was
caught: ``shlex.split`` of the unsanitized command failed, so the
classifier never treated the redirect as a write.
"""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from runtime.api.domain.lint_session_cwd_test_helpers import (
    seed_item,
    seed_item_claim,
)
from runtime.api.fixtures.machine_config_test import register_machine_checkout
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain import lint_lane_main_write
from yoke_core.domain.lint_lane_main_write_classify import is_write_operation
from yoke_core.domain.lint_lane_main_write_messages import ESCAPE_TOKEN

# Relative destination of the escaped ``cat > … <<PY`` write.
_CAT_HEREDOC_RELATIVE = (
    "packages/yoke-harness/src/yoke_harness/session_relay_codex_plan_limit.py"
)
_APOSTROPHE_BODY = "# don't land this module on main\nfrom pathlib import Path\n"


@pytest.fixture
def conn():
    with test_database() as c:
        yield c


@pytest.fixture
def repo(tmp_path):
    repo_path = tmp_path / "repo"
    (repo_path / ".worktrees").mkdir(parents=True)
    return repo_path


def _seed_lane(conn, repo, *, session_id="sid-lane", item_id=2013):
    register_machine_checkout(
        Path(repo).parent / "machine-config",
        Path(repo),
        project_id=1,
    )
    seed_item(
        conn,
        item_id=item_id,
        branch=f"YOK-{item_id}",
        status="implementing",
        repo_path=repo,
    )
    seed_item_claim(conn, session_id, item_id=item_id)
    worktree = repo / ".worktrees" / f"YOK-{item_id}"
    worktree.mkdir(parents=True, exist_ok=True)
    return worktree


def _cat_redirect_heredoc(relative: str, *, operator: str = ">") -> str:
    return f"cat {operator} {relative} <<PY\n{_APOSTROPHE_BODY}PY"


def _tee_heredoc(relative: str) -> str:
    return f"tee {relative} <<PY\n{_APOSTROPHE_BODY}PY"


def _after_opener_heredoc(relative: str) -> str:
    return f"cat <<PY > {relative}\n{_APOSTROPHE_BODY}PY"


def _bash(command: str, *, cwd: str) -> dict:
    return {
        "session_id": "sid-lane",
        "tool_name": "Bash",
        "cwd": cwd,
        "tool_input": {"command": command},
    }


@pytest.mark.parametrize(
    "command",
    [
        _cat_redirect_heredoc(_CAT_HEREDOC_RELATIVE),
        _cat_redirect_heredoc(_CAT_HEREDOC_RELATIVE, operator=">>"),
        _tee_heredoc(_CAT_HEREDOC_RELATIVE),
        _after_opener_heredoc(_CAT_HEREDOC_RELATIVE),
    ],
)
def test_apostrophe_heredoc_body_is_classified_as_a_write(command):
    assert is_write_operation("Bash", {"tool_input": {"command": command}})


class TestShellHeredocRedirectToMain:
    def _deny(self, conn, repo, command: str):
        worktree = _seed_lane(conn, repo)
        target = repo / _CAT_HEREDOC_RELATIVE
        target.parent.mkdir(parents=True, exist_ok=True)
        with mock.patch.object(lint_lane_main_write, "emit_denied", return_value=None):
            verdict = lint_lane_main_write.evaluate_pre_tool_use(
                _bash(command, cwd=str(repo)),
            )
        assert verdict.allow is False
        assert "BLOCKED" in verdict.reason
        assert str(target) in verdict.reason
        assert str(worktree / _CAT_HEREDOC_RELATIVE) in verdict.reason
        assert "Use instead:" in verdict.reason
        assert ESCAPE_TOKEN in verdict.reason
        return verdict

    def test_cat_redirect_heredoc_denies(self, conn, repo):
        self._deny(conn, repo, _cat_redirect_heredoc(_CAT_HEREDOC_RELATIVE))

    def test_append_redirect_heredoc_denies(self, conn, repo):
        self._deny(
            conn,
            repo,
            _cat_redirect_heredoc(_CAT_HEREDOC_RELATIVE, operator=">>"),
        )

    def test_tee_heredoc_denies(self, conn, repo):
        self._deny(conn, repo, _tee_heredoc(_CAT_HEREDOC_RELATIVE))

    def test_redirect_after_opener_denies(self, conn, repo):
        self._deny(conn, repo, _after_opener_heredoc(_CAT_HEREDOC_RELATIVE))

    def test_cat_heredoc_inside_lane_allows(self, conn, repo):
        worktree = _seed_lane(conn, repo)
        verdict = lint_lane_main_write.evaluate_pre_tool_use(
            _bash(
                _cat_redirect_heredoc(_CAT_HEREDOC_RELATIVE),
                cwd=str(worktree),
            )
        )
        assert verdict.allow is True

    def test_cat_heredoc_to_tmp_allows(self, conn, repo):
        _seed_lane(conn, repo)
        verdict = lint_lane_main_write.evaluate_pre_tool_use(
            _bash(
                _cat_redirect_heredoc("/tmp/yoke-lane-main-write-scratch.py"),
                cwd=str(repo),
            )
        )
        assert verdict.allow is True

    def test_escape_token_allows_cat_redirect_heredoc(self, conn, repo):
        _seed_lane(conn, repo)
        command = _cat_redirect_heredoc(_CAT_HEREDOC_RELATIVE) + f"\n{ESCAPE_TOKEN}\n"
        with mock.patch.object(lint_lane_main_write, "emit_escape_used") as emit:
            verdict = lint_lane_main_write.evaluate_pre_tool_use(
                _bash(command, cwd=str(repo)),
            )
        assert verdict.allow is True
        assert verdict.escape_used is True
        emit.assert_called_once()
