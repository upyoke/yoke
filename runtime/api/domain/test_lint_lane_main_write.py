"""Tests for :mod:`lint_lane_main_write`."""

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
from yoke_core.domain.lint_lane_main_write_messages import (
    ESCAPE_TOKEN,
    SUPPRESSION_TOKEN,
)
from runtime.harness.hook_runner.types import HookContext, Outcome


@pytest.fixture
def conn():
    with test_database() as c:
        yield c


@pytest.fixture
def repo(tmp_path):
    repo_path = tmp_path / "repo"
    (repo_path / ".worktrees").mkdir(parents=True)
    return repo_path


def _register_checkout(repo_path):
    register_machine_checkout(
        Path(repo_path).parent / "machine-config",
        Path(repo_path),
        project_id=1,
    )


def _seed_lane(conn, repo, *, session_id="sid-lane", item_id=2013, status="implementing"):
    _register_checkout(repo)
    seed_item(
        conn, item_id=item_id, branch=f"YOK-{item_id}", status=status,
        repo_path=repo,
    )
    seed_item_claim(conn, session_id, item_id=item_id)
    wt = repo / ".worktrees" / f"YOK-{item_id}"
    wt.mkdir(parents=True, exist_ok=True)
    return wt


def _python_heredoc_write(target: Path) -> str:
    return (
        "python3 - <<'PY'\n"
        "from pathlib import Path\n"
        f"target = Path({str(target)!r})\n"
        "target.write_text('changed')\n"
        "PY"
    )


class TestNoLane:
    def test_session_without_claims_allows_main_write(self, conn, repo):
        target = repo / "runtime/api/foo.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        verdict = lint_lane_main_write.evaluate_pre_tool_use({
            "session_id": "sid-none",
            "tool_name": "Write",
            "tool_input": {"file_path": str(target)},
        })
        assert verdict.allow is True


class TestMainWriteRefused:
    def test_write_to_main_checkout_denies(self, conn, repo):
        wt = _seed_lane(conn, repo)
        target = repo / "runtime/api/foo.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        with mock.patch.object(lint_lane_main_write, "emit_denied", return_value=None):
            verdict = lint_lane_main_write.evaluate_pre_tool_use({
                "session_id": "sid-lane",
                "tool_name": "Write",
                "tool_input": {"file_path": str(target)},
            })
        assert verdict.allow is False
        assert "BLOCKED" in verdict.reason
        assert str(wt) in verdict.reason
        assert str(target) in verdict.reason
        assert f"{wt}/runtime/api/foo.py" in verdict.reason

    def test_bash_redirect_to_main_denies(self, conn, repo):
        _seed_lane(conn, repo)
        target = repo / "runtime/api/foo.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        with mock.patch.object(lint_lane_main_write, "emit_denied", return_value=None):
            verdict = lint_lane_main_write.evaluate_pre_tool_use({
                "session_id": "sid-lane",
                "tool_name": "Bash",
                "cwd": str(repo),
                "tool_input": {"command": f"echo hi > {target}"},
            })
        assert verdict.allow is False
        assert str(target) in verdict.reason

    def test_python_heredoc_write_to_main_denies(self, conn, repo):
        _seed_lane(conn, repo)
        relative_target = Path("runtime/api/foo.py")
        target = repo / relative_target
        target.parent.mkdir(parents=True, exist_ok=True)
        with mock.patch.object(lint_lane_main_write, "emit_denied", return_value=None):
            verdict = lint_lane_main_write.evaluate_pre_tool_use({
                "session_id": "sid-lane",
                "tool_name": "Bash",
                "cwd": str(repo),
                "tool_input": {"command": _python_heredoc_write(relative_target)},
            })
        assert verdict.allow is False
        assert str(target) in verdict.reason


class TestEscape:
    def test_escape_token_allows_and_records(self, conn, repo):
        _seed_lane(conn, repo)
        target = repo / "runtime/api/foo.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        with mock.patch.object(lint_lane_main_write, "emit_escape_used") as emit_escape:
            verdict = lint_lane_main_write.evaluate_pre_tool_use({
                "session_id": "sid-lane",
                "tool_name": "Write",
                "tool_input": {
                    "file_path": str(target),
                    "content": f"change {ESCAPE_TOKEN}",
                },
            })
        assert verdict.allow is True
        assert verdict.escape_used is True
        emit_escape.assert_called_once()


class TestRegisteredAdapters:
    def test_yoke_sessions_touch_allows_without_escape(self, conn, repo):
        _seed_lane(conn, repo)
        verdict = lint_lane_main_write.evaluate_pre_tool_use({
            "session_id": "sid-lane",
            "tool_name": "Bash",
            "cwd": str(repo),
            "tool_input": {"command": "yoke sessions touch --mode usher"},
        })
        assert verdict.allow is True
        assert verdict.escape_used is False

    def test_yoke_deployment_runs_allows_without_escape(self, conn, repo):
        _seed_lane(conn, repo)
        verdict = lint_lane_main_write.evaluate_pre_tool_use({
            "session_id": "sid-lane",
            "tool_name": "Bash",
            "cwd": str(repo),
            "tool_input": {
                "command": "yoke deployment-runs start-for-item YOK-2094",
            },
        })
        assert verdict.allow is True
        assert verdict.escape_used is False


class TestStrandedLane:
    def test_missing_lane_path_advises_and_allows(self, conn, repo):
        wt = _seed_lane(conn, repo)
        target = repo / "runtime/api/foo.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        # Genuinely stranded: recorded path gone AND claim heartbeat stale.
        wt.rmdir()
        conn.execute(
            "UPDATE work_claims SET last_heartbeat = %s WHERE session_id = %s",
            ("2000-01-01T00:00:00Z", "sid-lane"),
        )
        conn.commit()
        with mock.patch.object(
            lint_lane_main_write, "emit_stranded_lane_advisory",
        ) as emit_advisory:
            verdict = lint_lane_main_write.evaluate_pre_tool_use({
                "session_id": "sid-lane",
                "tool_name": "Write",
                "tool_input": {"file_path": str(target)},
            })
        assert verdict.allow is True
        emit_advisory.assert_called_once()
        assert emit_advisory.call_args.kwargs["lane_path"] == str(wt)


class TestUnaffectedCases:
    def test_write_inside_lane_allows(self, conn, repo):
        wt = _seed_lane(conn, repo)
        target = wt / "runtime/api/foo.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        verdict = lint_lane_main_write.evaluate_pre_tool_use({
            "session_id": "sid-lane",
            "tool_name": "Write",
            "tool_input": {"file_path": str(target)},
        })
        assert verdict.allow is True

    def test_python_heredoc_write_inside_lane_allows(self, conn, repo):
        wt = _seed_lane(conn, repo)
        relative_target = Path("runtime/api/foo.py")
        target = wt / relative_target
        target.parent.mkdir(parents=True, exist_ok=True)
        verdict = lint_lane_main_write.evaluate_pre_tool_use({
            "session_id": "sid-lane",
            "tool_name": "Bash",
            "cwd": str(wt),
            "tool_input": {"command": _python_heredoc_write(relative_target)},
        })
        assert verdict.allow is True

    def test_free_path_allows(self, conn, repo):
        _seed_lane(conn, repo)
        verdict = lint_lane_main_write.evaluate_pre_tool_use({
            "session_id": "sid-lane",
            "tool_name": "Write",
            "tool_input": {"file_path": "/tmp/yoke-scratch.txt"},
        })
        assert verdict.allow is True

    def test_generated_view_board_allows(self, conn, repo):
        _seed_lane(conn, repo)
        target = repo / ".yoke" / "BOARD.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        verdict = lint_lane_main_write.evaluate_pre_tool_use({
            "session_id": "sid-lane",
            "tool_name": "Write",
            "tool_input": {"file_path": str(target)},
        })
        assert verdict.allow is True

    def test_pre_implementing_status_allows_main(self, conn, repo):
        _register_checkout(repo)
        seed_item(
            conn, item_id=2013, branch="YOK-2013", status="idea",
            repo_path=repo,
        )
        seed_item_claim(conn, "sid-lane", item_id=2013)
        (repo / ".worktrees" / "YOK-2013").mkdir(parents=True, exist_ok=True)
        target = repo / "runtime/api/foo.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        verdict = lint_lane_main_write.evaluate_pre_tool_use({
            "session_id": "sid-lane",
            "tool_name": "Write",
            "tool_input": {"file_path": str(target)},
        })
        assert verdict.allow is True

    def test_bash_read_only_to_main_allows(self, conn, repo):
        _seed_lane(conn, repo)
        target = repo / "runtime/api/foo.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# stub\n")
        verdict = lint_lane_main_write.evaluate_pre_tool_use({
            "session_id": "sid-lane",
            "tool_name": "Bash",
            "cwd": str(repo),
            "tool_input": {"command": f"cat {target}"},
        })
        assert verdict.allow is True


class TestSuppressionAndSubagent:
    def test_suppression_token_does_not_unblock(self, conn, repo):
        _seed_lane(conn, repo)
        target = repo / "runtime/api/foo.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        with mock.patch.object(lint_lane_main_write, "emit_denied", return_value=None):
            verdict = lint_lane_main_write.evaluate_pre_tool_use({
                "session_id": "sid-lane",
                "tool_name": "Bash",
                "cwd": str(repo),
                "tool_input": {
                    "command": f"touch {target} {SUPPRESSION_TOKEN}",
                },
            })
        assert verdict.allow is False
        assert verdict.suppression_attempted is True

    def test_subagent_context_uses_same_session_claim(self, conn, repo):
        wt = _seed_lane(conn, repo)
        target = repo / "runtime/api/foo.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        with mock.patch.dict("os.environ", {"YOKE_HOOK_AGENT_TYPE": "engineer"}):
            with mock.patch.object(lint_lane_main_write, "emit_denied", return_value=None):
                record = HookContext(
                    event_name="PreToolUse",
                    executor_family="claude",
                    executor_surface="claude",
                    payload={
                        "session_id": "sid-lane",
                        "tool_name": "Write",
                        "tool_input": {"file_path": str(target)},
                    },
                    tool_name="Write",
                    cwd=str(repo),
                    session_id="sid-lane",
                )
                decision = lint_lane_main_write.evaluate(record)
        assert decision.outcome is Outcome.DENY
        assert str(wt) in (decision.message or "")


class TestHookOrdering:
    def test_guard_is_registered_after_session_cwd(self):
        from yoke_contracts.hook_runner.hook_ordering import ordered_pipeline_for

        edit_chain = ordered_pipeline_for("PreToolUse", "Edit")
        write_chain = ordered_pipeline_for("PreToolUse", "Write")
        bash_chain = ordered_pipeline_for("PreToolUse", "Bash")
        assert edit_chain.index("yoke_core.domain.lint_lane_main_write") > edit_chain.index(
            "yoke_core.domain.lint_session_cwd"
        )
        assert write_chain.index("yoke_core.domain.lint_lane_main_write") > write_chain.index(
            "yoke_core.domain.lint_session_cwd"
        )
        assert bash_chain.index("yoke_core.domain.lint_lane_main_write") > bash_chain.index(
            "yoke_core.domain.lint_session_cwd"
        )
