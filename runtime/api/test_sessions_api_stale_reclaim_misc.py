"""Stale-reclaim, registry seeder, and sweep-event tests.

Includes executor-aware stale-session cleanup, idempotent event-registry
seeding, and HarnessSessionStaleSweepCompleted event coverage.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

from runtime.api.test_sessions import _create_schema, _register, conn  # noqa: F401  (pytest fixture)
from yoke_core.domain.sessions import (
    EVENT_HARNESS_SESSION_STALE_SWEEP_COMPLETED,
    claim_work,
    clean_stale_harness_sessions,
)
from runtime.api.sessions_api_stale_test_helpers import (
    EVENTS_TABLE_FOR_STALE_DETECTION,
    _ago_minutes,
    apply_ddl_statements,
)
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


_REGISTRY_SCHEMA = """
    CREATE TABLE event_registry (
        event_name TEXT PRIMARY KEY,
        event_kind TEXT NOT NULL,
        event_type TEXT NOT NULL,
        owner_service TEXT NOT NULL,
        description TEXT NOT NULL,
        context_schema TEXT,
        severity_default TEXT NOT NULL DEFAULT 'INFO',
        added_in TEXT,
        status TEXT NOT NULL DEFAULT 'active'
    );
"""


def _apply_registry_schema() -> None:
    conn = connect_test_db("")
    try:
        apply_ddl_statements(conn, _REGISTRY_SCHEMA)
        conn.commit()
    finally:
        conn.close()


@contextmanager
def _registry_conn(tmp_path: Path, *, with_table: bool = True):
    apply_schema = _apply_registry_schema if with_table else (lambda: None)
    with init_test_db(tmp_path, apply_schema=apply_schema) as db_path:
        c = connect_test_db(db_path)
        try:
            yield c
        finally:
            c.close()


class TestStaleReclaimYOK1350:
    """AC-9/10/11: executor-aware stale-session cleanup."""

    @pytest.fixture
    def conn_with_events(self, conn):
        apply_ddl_statements(conn, EVENTS_TABLE_FOR_STALE_DETECTION)
        return conn

    def test_codex_session_between_turns_is_skipped(self, conn_with_events):
        """AC-11: Codex sessions that are merely between turns are not reclaimed."""
        conn = conn_with_events
        _register(conn, session_id="codex-idle", executor="codex")
        # Simulate a Codex session that hasn't heartbeated for 25 minutes but
        # under the 60-minute codex TTL override.
        conn.execute(
            """UPDATE harness_sessions
               SET last_heartbeat = %s
               WHERE session_id = 'codex-idle'""",
            (_ago_minutes(25),),
        )
        conn.commit()

        result = clean_stale_harness_sessions(conn, stale_threshold_minutes=20)

        assert result["total_reclaimed"] == 0
        ids = {e["session_id"] for e in result["skipped_between_turns"]}
        assert ids == {"codex-idle"}

    def test_codex_session_past_override_is_reclaimed(self, conn_with_events):
        """AC-11: Codex session past the 60-minute override is still reclaimed."""
        conn = conn_with_events
        _register(conn, session_id="codex-dead", executor="codex")
        conn.execute(
            """UPDATE harness_sessions
               SET last_heartbeat = %s
               WHERE session_id = 'codex-dead'""",
            (_ago_minutes(90),),
        )
        conn.commit()

        result = clean_stale_harness_sessions(conn, stale_threshold_minutes=20)
        assert result["total_reclaimed"] == 1

    def test_codex_surface_session_uses_codex_ttl_override(self, conn_with_events):
        """codex-* surface executors inherit the coarse Codex TTL."""
        conn = conn_with_events
        _register(conn, session_id="codex-desktop-idle", executor="codex-desktop")
        conn.execute(
            """UPDATE harness_sessions
               SET last_heartbeat = %s
               WHERE session_id = 'codex-desktop-idle'""",
            (_ago_minutes(25),),
        )
        conn.commit()

        result = clean_stale_harness_sessions(conn, stale_threshold_minutes=20)

        assert result["total_reclaimed"] == 0
        ids = {e["session_id"] for e in result["skipped_between_turns"]}
        assert ids == {"codex-desktop-idle"}

    def test_claude_stale_uses_base_ttl(self, conn_with_events):
        """AC-11: Claude sessions use the base TTL without executor override."""
        conn = conn_with_events
        _register(conn, session_id="claude-stale", executor="claude-code")
        conn.execute(
            """UPDATE harness_sessions
               SET last_heartbeat = %s
               WHERE session_id = 'claude-stale'""",
            (_ago_minutes(25),),
        )
        conn.commit()

        result = clean_stale_harness_sessions(conn, stale_threshold_minutes=20)
        assert result["total_reclaimed"] == 1

    def test_latest_event_keeps_session_alive(self, conn_with_events):
        """AC-10: session with stale heartbeat but fresh events is not reclaimed."""
        conn = conn_with_events
        _register(conn, session_id="event-alive", executor="claude-code")
        conn.execute(
            """UPDATE harness_sessions
               SET last_heartbeat = %s
               WHERE session_id = 'event-alive'""",
            (_ago_minutes(30),),
        )
        conn.execute(
            """UPDATE harness_sessions
               SET last_tool_call_at = %s,
                   tool_call_count = COALESCE(tool_call_count, 0) + 1
               WHERE session_id = 'event-alive'""",
            (_ago_minutes(2),),
        )
        conn.commit()

        result = clean_stale_harness_sessions(conn, stale_threshold_minutes=20)
        assert result["total_reclaimed"] == 0

    def test_emits_stale_session_reclaimed_event(self, conn_with_events):
        """AC-10: reclaim emits HarnessSessionStaleReclaimed with required fields."""
        conn = conn_with_events
        _register(conn, session_id="stale-ev", executor="claude-code")
        conn.execute(
            """UPDATE harness_sessions
               SET last_heartbeat = %s
               WHERE session_id = 'stale-ev'""",
            (_ago_minutes(30),),
        )
        conn.commit()
        claim_work(conn, session_id="stale-ev", item_id="YOK-777")
        stale_claim_ts = _ago_minutes(30)
        conn.execute(
            """UPDATE work_claims
               SET claimed_at = %s, last_heartbeat = %s
               WHERE session_id = 'stale-ev'""",
            (stale_claim_ts, stale_claim_ts),
        )
        conn.commit()

        with patch("yoke_core.domain.sessions_analytics._emit_event") as mock_emit:
            clean_stale_harness_sessions(conn, stale_threshold_minutes=20)

        stale_calls = [
            c for c in mock_emit.call_args_list
            if c.args and c.args[0] == "HarnessSessionStaleReclaimed"
        ]
        assert len(stale_calls) == 1
        ctx = stale_calls[0].kwargs["context"]
        assert ctx["executor"] == "claude-code"
        assert "stale_minutes" in ctx
        assert "last_event_at" in ctx
        assert ctx["released_claim_count"] == 1
        assert ctx["effective_ttl_minutes"] == 20


class TestRegistrySeeder:
    """HarnessSessionHookFailed + HarnessSessionStaleReclaimed idempotent seeding."""

    def test_idempotent_seed(self, tmp_path):
        from yoke_core.domain.sessions import ensure_session_event_registry_entries

        with _registry_conn(tmp_path) as c:
            ensure_session_event_registry_entries(c)
            ensure_session_event_registry_entries(c)  # idempotent

            rows = c.execute(
                "SELECT event_name, severity_default, added_in FROM event_registry "
                "WHERE event_name IN "
                "('HarnessSessionHookFailed', 'HarnessSessionStaleReclaimed')",
            ).fetchall()
            names = {r["event_name"] for r in rows}
            assert names == {"HarnessSessionHookFailed", "HarnessSessionStaleReclaimed"}
            sev = {r["event_name"]: r["severity_default"] for r in rows}
            assert sev["HarnessSessionHookFailed"] == "WARN"
            assert sev["HarnessSessionStaleReclaimed"] == "INFO"

    def test_missing_registry_table_is_noop(self, tmp_path):
        from yoke_core.domain.sessions import ensure_session_event_registry_entries

        with _registry_conn(tmp_path, with_table=False) as c:
            ensure_session_event_registry_entries(c)  # must not raise


class TestStaleSessionSweepEvent:
    """HarnessSessionStaleSweepCompleted event."""

    _SWEEP_EVENT_TABLES = """
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY,
            event_name TEXT NOT NULL,
            event_kind TEXT,
            event_type TEXT,
            source_type TEXT,
            session_id TEXT,
            item_id TEXT,
            task_num INTEGER,
            project_id INTEGER DEFAULT 1,
            severity TEXT DEFAULT 'INFO',
            outcome TEXT DEFAULT 'completed',
            envelope TEXT,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS event_registry (
            event_name TEXT PRIMARY KEY,
            event_kind TEXT,
            event_type TEXT,
            owner_service TEXT,
            description TEXT,
            context_schema TEXT,
            severity_default TEXT,
            added_in TEXT,
            status TEXT DEFAULT 'active'
        );
    """

    @pytest.fixture
    def conn(self, conn):
        # Sweep-event emission also reads the events + event_registry tables,
        # which the shared session-schema fixture does not build.
        apply_ddl_statements(conn, self._SWEEP_EVENT_TABLES)
        conn.commit()
        return conn

    @patch("yoke_core.domain.sessions_analytics._emit_session_event")
    def test_sweep_emits_event_zero_reclaims(self, mock_emit, conn):
        """AC-8: Sweep emits event even with no sessions to reclaim."""
        result = clean_stale_harness_sessions(conn)
        assert result["total_reclaimed"] == 0
        calls = [c for c in mock_emit.call_args_list
                 if c[0][0] == EVENT_HARNESS_SESSION_STALE_SWEEP_COMPLETED]
        assert len(calls) == 1
        ctx = calls[0][1]["context"]
        assert ctx["total_scanned"] == 0
        assert ctx["total_reclaimed"] == 0
        assert "sweep_duration_ms" in ctx
