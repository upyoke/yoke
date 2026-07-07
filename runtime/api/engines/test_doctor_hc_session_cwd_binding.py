"""Tests for HC-session-cwd-binding (claim-based authority shape)."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import pytest

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.machine_config_test import register_machine_checkout
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from yoke_core.engines import doctor_hc_session_cwd_binding as hc_module
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


# ---------------------------------------------------------------------------
# Fixture helpers — minimal in-memory DB carrying just the columns the HC reads
# ---------------------------------------------------------------------------


def _disposable_pg_db(ddl: str) -> Any:
    name = pg_testdb.create_test_database()
    conn = pg_testdb.connect_test_database(name)
    if ddl:
        apply_fixture_ddl(conn, ddl)
    return pg_testdb.drop_database_on_close(conn, name)


def _make_conn() -> Any:
    return _disposable_pg_db(
        """
        CREATE TABLE harness_sessions (
            session_id TEXT PRIMARY KEY,
            mode TEXT,
            current_item_id TEXT,
            ended_at TEXT
        );
        CREATE TABLE projects (
            id INTEGER PRIMARY KEY,
            slug TEXT UNIQUE
        );
        CREATE TABLE items (
            id INTEGER PRIMARY KEY,
            worktree TEXT,
            project_id INTEGER DEFAULT 1
        );
        CREATE TABLE epic_tasks (
            epic_id INTEGER NOT NULL,
            task_num INTEGER NOT NULL,
            worktree TEXT,
            PRIMARY KEY (epic_id, task_num)
        );
        CREATE TABLE work_claims (
            id INTEGER PRIMARY KEY,
            session_id TEXT,
            target_kind TEXT,
            item_id INTEGER,
            epic_id INTEGER,
            task_num INTEGER,
            process_key TEXT,
            released_at TEXT
        );
        CREATE TABLE events (
            id INTEGER PRIMARY KEY,
            session_id TEXT,
            event_name TEXT,
            envelope TEXT
        );
        """
    )


def _add_project(conn, project_id="yoke", checkout_path="/repo/yoke"):
    conn.execute(
        "INSERT INTO projects (id, slug) VALUES (%s, %s)",
        (1 if project_id == "yoke" else 999, project_id),
    )
    register_machine_checkout(
        Path(tempfile.mkdtemp(prefix="yoke-machine-config-")),
        Path(checkout_path),
        1 if project_id == "yoke" else 999,
        create_checkout=False,
    )
    conn.commit()


def _add_session(conn, session_id, mode="advance", current_item_id="9001"):
    conn.execute(
        "INSERT INTO harness_sessions "
        "(session_id, mode, current_item_id, ended_at) "
        "VALUES (%s, %s, %s, NULL)",
        (session_id, mode, current_item_id),
    )
    conn.commit()


def _add_item(conn, item_id, worktree="YOK-9001", project="yoke"):
    project_id = 1 if project == "yoke" else 999
    conn.execute(
        "INSERT INTO items (id, worktree, project_id) VALUES (%s, %s, %s)",
        (item_id, worktree, project_id),
    )
    conn.commit()


def _add_work_claim(conn, session_id, item_id, target_kind="item"):
    conn.execute(
        "INSERT INTO work_claims "
        "(session_id, target_kind, item_id, released_at) "
        "VALUES (%s, %s, %s, NULL)",
        (session_id, target_kind, item_id),
    )
    conn.commit()


def _add_tool_event(conn, session_id, cwd):
    envelope = json.dumps({"cwd": cwd})
    conn.execute(
        "INSERT INTO events (session_id, event_name, envelope) "
        "VALUES (%s, 'HarnessToolCallStarted', %s)",
        (session_id, envelope),
    )
    conn.commit()


@pytest.fixture
def silenced_emit(monkeypatch):
    captured = []

    def _capture(**kwargs):
        captured.append(kwargs)

    monkeypatch.setattr(hc_module, "emit_health_check_failed", _capture)
    # Empty the free-path allowlist so pytest tmp paths (under /var/folders
    # on macOS) don't accidentally pass validation. The HC validates against
    # the live FREE_PATH_PREFIXES; tests want a clean slate.
    from yoke_core.domain import lint_session_cwd_validate
    monkeypatch.setattr(lint_session_cwd_validate, "FREE_PATH_PREFIXES", ())
    return captured


# ---------------------------------------------------------------------------
# HC happy / sad paths
# ---------------------------------------------------------------------------


class TestSessionCwdBindingHC:
    def test_no_active_sessions_passes(self, silenced_emit):
        conn = _make_conn()
        rec = RecordCollector()

        hc_module.hc_session_cwd_binding(conn, DoctorArgs(), rec)

        assert len(rec.results) == 1
        assert rec.results[0].result == "PASS"
        assert "no active sessions with work claims" in rec.results[0].detail
        assert silenced_emit == []

    def test_single_matched_session_passes(self, tmp_path, silenced_emit):
        main = tmp_path / "main"
        worktree = main / ".worktrees" / "YOK-9001"
        worktree.mkdir(parents=True)
        conn = _make_conn()
        _add_project(conn, checkout_path=str(main))
        _add_item(conn, 9001, worktree="YOK-9001")
        _add_session(conn, "sess-A", current_item_id="9001")
        _add_work_claim(conn, "sess-A", 9001)
        _add_tool_event(conn, "sess-A", str(worktree))
        rec = RecordCollector()

        hc_module.hc_session_cwd_binding(conn, DoctorArgs(), rec)

        assert rec.results[0].result == "PASS"
        assert "1 matched" in rec.results[0].detail
        assert silenced_emit == []

    def test_single_mismatched_session_fails(self, tmp_path, silenced_emit):
        main = tmp_path / "main"
        (main / ".worktrees" / "YOK-9001").mkdir(parents=True)
        outside = tmp_path / "outside"
        outside.mkdir()
        conn = _make_conn()
        _add_project(conn, checkout_path=str(main))
        _add_item(conn, 9001, worktree="YOK-9001")
        _add_session(conn, "sess-bad", current_item_id="9001")
        _add_work_claim(conn, "sess-bad", 9001)
        _add_tool_event(conn, "sess-bad", str(outside))
        rec = RecordCollector()

        hc_module.hc_session_cwd_binding(conn, DoctorArgs(), rec)

        assert rec.results[0].result == "FAIL"
        assert "sess-bad" in rec.results[0].detail
        assert str(outside) in rec.results[0].detail
        assert len(silenced_emit) == 1
        emitted = silenced_emit[0]
        assert emitted["session_id"] == "sess-bad"
        assert emitted["claim_count"] == 1
        assert "offending_target" in emitted

    def test_multiple_sessions_one_mismatch(self, tmp_path, silenced_emit):
        main = tmp_path / "main"
        worktree_a = main / ".worktrees" / "YOK-9001"
        worktree_b = main / ".worktrees" / "YOK-9002"
        worktree_a.mkdir(parents=True)
        worktree_b.mkdir(parents=True)
        outside = tmp_path / "outside"
        outside.mkdir()
        conn = _make_conn()
        _add_project(conn, checkout_path=str(main))
        _add_item(conn, 9001, worktree="YOK-9001")
        _add_item(conn, 9002, worktree="YOK-9002")
        _add_session(conn, "sess-good", current_item_id="9001")
        _add_session(conn, "sess-bad", current_item_id="9002")
        _add_work_claim(conn, "sess-good", 9001)
        _add_work_claim(conn, "sess-bad", 9002)
        _add_tool_event(conn, "sess-good", str(worktree_a))
        _add_tool_event(conn, "sess-bad", str(outside))
        rec = RecordCollector()

        hc_module.hc_session_cwd_binding(conn, DoctorArgs(), rec)

        assert rec.results[0].result == "FAIL"
        assert "sess-bad" in rec.results[0].detail
        assert "sess-good" not in rec.results[0].detail
        assert len(silenced_emit) == 1
        assert silenced_emit[0]["session_id"] == "sess-bad"

    def test_session_without_telemetry_marked_unknown(
        self, tmp_path, silenced_emit
    ):
        main = tmp_path / "main"
        (main / ".worktrees" / "YOK-9001").mkdir(parents=True)
        conn = _make_conn()
        _add_project(conn, checkout_path=str(main))
        _add_item(conn, 9001, worktree="YOK-9001")
        _add_session(conn, "sess-mute", current_item_id="9001")
        _add_work_claim(conn, "sess-mute", 9001)
        rec = RecordCollector()

        hc_module.hc_session_cwd_binding(conn, DoctorArgs(), rec)

        assert rec.results[0].result == "PASS"
        assert "no recent cwd telemetry" in rec.results[0].detail
        assert "1 unknown" in rec.results[0].detail
        assert silenced_emit == []

    def test_missing_harness_sessions_table_passes(self, silenced_emit):
        conn = _disposable_pg_db("")
        rec = RecordCollector()

        hc_module.hc_session_cwd_binding(conn, DoctorArgs(), rec)

        assert rec.results[0].result == "PASS"
        assert "missing" in rec.results[0].detail
