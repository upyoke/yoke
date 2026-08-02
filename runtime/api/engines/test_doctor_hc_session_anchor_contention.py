"""Unit tests for ``HC-session-anchor-contention``.

Each test seeds a tmp session-anchor registry plus a minimal
``harness_sessions`` table in a disposable Postgres test database, runs the
HC, and asserts the recorded verdict.
"""

from __future__ import annotations

import json
from typing import Optional

import pytest

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from yoke_project_checks.check_session_anchor_contention import (
    HC_SLUG,
    PROJECT_HEALTH_CHECKS,
    hc_session_anchor_contention,
)
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector

_HARNESS_SESSIONS_DDL = """
CREATE TABLE harness_sessions (
    session_id TEXT PRIMARY KEY,
    executor TEXT NOT NULL DEFAULT 'claude-code',
    offered_at TEXT NOT NULL,
    last_heartbeat TEXT NOT NULL,
    ended_at TEXT
);
"""

_WHEN = "2026-05-20T00:00:00+00:00"
_START = "Wed Jun 10 14:05:41 2026"


@pytest.fixture
def sessions_conn():
    name = pg_testdb.create_test_database()
    conn = pg_testdb.drop_database_on_close(
        pg_testdb.connect_test_database(name), name
    )
    apply_fixture_ddl(conn, _HARNESS_SESSIONS_DDL)
    yield conn
    conn.close()


@pytest.fixture
def registry(tmp_path, monkeypatch):
    directory = tmp_path / "session-anchors"
    directory.mkdir()
    monkeypatch.setattr(
        "yoke_core.domain.session_process_anchors.anchors_dir",
        lambda: directory,
    )
    # The registry only reports on markers whose anchor process is alive.
    monkeypatch.setattr(
        "yoke_project_checks.check_session_anchor_contention"
        "._anchor_process_live",
        lambda record: record.get("anchor_start_time") == _START,
    )
    return directory


def _seed_session(conn, session_id: str, *, ended_at: Optional[str] = None):
    conn.execute(
        "INSERT INTO harness_sessions "
        "(session_id, offered_at, last_heartbeat, ended_at) "
        "VALUES (%s, %s, %s, %s)",
        (session_id, _WHEN, _WHEN, ended_at),
    )


def _seed_marker(registry, pid: int, contenders, *, start: str = _START):
    (registry / f"{pid}.json").write_text(json.dumps({
        "session_id": "",
        "anchor_pid": pid,
        "anchor_start_time": start,
        "shared_by_multiple_sessions": True,
        "contending_session_ids": list(contenders),
        "last_writer_argv": "yoke hook evaluate PreToolUse",
    }))


def _run(conn):
    rec = RecordCollector()
    hc_session_anchor_contention(conn, DoctorArgs(), rec)
    assert len(rec.results) == 1
    return rec.results[0]


def test_module_declares_the_check_for_discovery():
    assert [check.slug for check in PROJECT_HEALTH_CHECKS] == [HC_SLUG]


def test_no_markers_passes(sessions_conn, registry):
    result = _run(sessions_conn)
    assert result.result == "PASS"


def test_two_live_contenders_is_expected_fail_closed_state(
    sessions_conn, registry,
):
    _seed_session(sessions_conn, "sess-a")
    _seed_session(sessions_conn, "sess-b")
    _seed_marker(registry, 200, ["sess-a", "sess-b"])
    result = _run(sessions_conn)
    assert result.result == "PASS"


def test_marker_with_one_live_contender_warns(sessions_conn, registry):
    _seed_session(sessions_conn, "sess-a")
    _seed_session(sessions_conn, "sess-b", ended_at=_WHEN)
    _seed_marker(registry, 200, ["sess-a", "sess-b"])
    result = _run(sessions_conn)
    assert result.result == "WARN"
    assert "sess-a" in result.detail
    assert "yoke hook evaluate" in result.detail


def test_blank_marker_without_contenders_warns(sessions_conn, registry):
    _seed_marker(registry, 200, [])
    result = _run(sessions_conn)
    assert result.result == "WARN"
    assert "unrecorded" in result.detail


def test_marker_for_a_dead_process_is_ignored(sessions_conn, registry):
    _seed_marker(registry, 200, ["sess-a", "sess-b"], start="gone")
    result = _run(sessions_conn)
    assert result.result == "PASS"


def test_unregistered_contenders_count_as_live(sessions_conn, registry):
    # The healer keeps unknowns, so the check must not claim a heal it
    # would not perform.
    _seed_marker(registry, 200, ["sess-x", "sess-y"])
    result = _run(sessions_conn)
    assert result.result == "PASS"
