"""Transport-resolution and write-classification tests for lane-main-write.

These cases exercise the real filesystem probe and extractor rather than
stubbing them: an https-shaped recorded path is absent on this machine,
and shell tokens are classified by the production helpers.
"""

from __future__ import annotations

from pathlib import Path
from unittest import mock
from uuid import uuid4

import pytest

from runtime.api.domain.lint_session_cwd_test_helpers import (
    seed_item,
    seed_item_claim,
)
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain import lint_lane_main_write
from yoke_core.domain.lint_lane_main_write_emit import (
    stranded_advisory_already_recorded,
)


@pytest.fixture
def conn():
    with test_database() as c:
        yield c


@pytest.fixture
def repo(tmp_path):
    repo_path = tmp_path / "repo"
    (repo_path / ".worktrees").mkdir(parents=True)
    return repo_path


def _seed_lane(conn, repo, *, session_id="sid-lane", item_id=2013, mkdir=True):
    seed_item(
        conn, item_id=item_id, branch=f"YOK-{item_id}", status="implementing",
        repo_path=repo,
    )
    seed_item_claim(conn, session_id, item_id=item_id)
    wt = repo / ".worktrees" / f"YOK-{item_id}"
    if mkdir:
        wt.mkdir(parents=True, exist_ok=True)
    return wt


def _stale_claim(conn, session_id="sid-lane"):
    conn.execute(
        "UPDATE work_claims SET last_heartbeat = %s WHERE session_id = %s",
        ("2000-01-01T00:00:00Z", session_id),
    )
    conn.commit()


class TestHttpsShapeDeniesRecordedLane:
    def test_fresh_claim_denies_when_path_absent_on_evaluator(self, conn):
        repo = Path("/client-host/yoke")
        wt = _seed_lane(conn, repo, mkdir=False)
        assert wt.is_dir() is False
        target = repo / "runtime/api/foo.py"
        with mock.patch.object(lint_lane_main_write, "emit_denied", return_value=None):
            verdict = lint_lane_main_write.evaluate_pre_tool_use({
                "session_id": "sid-lane",
                "tool_name": "Write",
                "tool_input": {"file_path": str(target)},
            })
        assert verdict.allow is False
        assert str(wt) in verdict.reason
        assert str(target) in verdict.reason


class TestWriteClassification:
    def test_heredoc_without_path_write_allows(self, conn, repo):
        _seed_lane(conn, repo)
        verdict = lint_lane_main_write.evaluate_pre_tool_use({
            "session_id": "sid-lane",
            "tool_name": "Bash",
            "cwd": str(repo),
            "tool_input": {"command": "python3 - <<'PY'\nprint('hi')\nPY"},
        })
        assert verdict.allow is True

    def test_glued_redirect_to_main_denies(self, conn, repo):
        _seed_lane(conn, repo)
        target = repo / "AGENTS.md"
        with mock.patch.object(lint_lane_main_write, "emit_denied", return_value=None):
            verdict = lint_lane_main_write.evaluate_pre_tool_use({
                "session_id": "sid-lane",
                "tool_name": "Bash",
                "cwd": str(repo),
                "tool_input": {"command": f"echo x >{target}"},
            })
        assert verdict.allow is False
        assert str(target) in verdict.reason

    def test_stderr_fd_dup_does_not_deny(self, conn, repo):
        _seed_lane(conn, repo)
        verdict = lint_lane_main_write.evaluate_pre_tool_use({
            "session_id": "sid-lane",
            "tool_name": "Bash",
            "cwd": str(repo),
            "tool_input": {
                "command": "echo x >/tmp/lane-main-write-out 2>&1",
            },
        })
        assert verdict.allow is True


class TestStrandedAdvisoryBounds:
    def test_read_only_call_does_not_emit_advisory(self, conn, repo):
        wt = _seed_lane(conn, repo)
        wt.rmdir()
        _stale_claim(conn)
        with mock.patch.object(
            lint_lane_main_write, "emit_stranded_lane_advisory",
        ) as emit_advisory:
            verdict = lint_lane_main_write.evaluate_pre_tool_use({
                "session_id": "sid-lane",
                "tool_name": "Bash",
                "cwd": str(repo),
                "tool_input": {"command": "ls"},
            })
        assert verdict.allow is True
        emit_advisory.assert_not_called()

    def test_advisory_emits_once_per_session_item(self, conn, repo):
        wt = _seed_lane(conn, repo)
        target = repo / "runtime/api/foo.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        wt.rmdir()
        _stale_claim(conn)
        conn.execute(
            "INSERT INTO events (event_id, source_type, session_id, severity, "
            "event_kind, event_type, event_name, item_id, created_at) "
            "VALUES (%s, 'hook', %s, 'INFO', 'lifecycle', 'session_cwd', "
            "%s, %s, %s)",
            (
                str(uuid4()),
                "sid-lane",
                "LaneMainWriteStrandedLane",
                "2013",
                "2026-01-01T00:00:00Z",
            ),
        )
        conn.commit()
        assert stranded_advisory_already_recorded(
            conn, session_id="sid-lane", item_id=2013,
        ) is True
        with mock.patch.object(
            lint_lane_main_write, "emit_stranded_lane_advisory",
        ) as emit_advisory:
            verdict = lint_lane_main_write.evaluate_pre_tool_use({
                "session_id": "sid-lane",
                "tool_name": "Write",
                "tool_input": {"file_path": str(target)},
            })
        assert verdict.allow is True
        emit_advisory.assert_not_called()
