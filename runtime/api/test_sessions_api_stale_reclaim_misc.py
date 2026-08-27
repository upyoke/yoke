# ruff: noqa: F811
"""Stale-reclaim, registry seeder, and sweep-event tests.

Includes holdings-aware stale-session cleanup, idempotent event-registry
seeding, and HarnessSessionStaleSweepCompleted event coverage.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

from runtime.api.test_sessions import (
    _insert_claimable_items,
    _register,
    conn,  # noqa: F401
)
from yoke_core.domain.sessions import (
    EVENT_HARNESS_SESSION_STALE_SWEEP_COMPLETED,
    claim_work,
    clean_stale_harness_sessions,
)
from yoke_core.domain.sessions_analytics_core import (
    DEFAULT_STALE_WITH_HOLDINGS_THRESHOLD_MINUTES,
)

_PAST_HOLDINGS_TTL = DEFAULT_STALE_WITH_HOLDINGS_THRESHOLD_MINUTES + 60
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


class TestEmptySessionStaleCleanup:
    """Empty-session stale cleanup uses one base TTL on every harness."""

    @pytest.fixture
    def conn_with_events(self, conn):
        apply_ddl_statements(conn, EVENTS_TABLE_FOR_STALE_DETECTION)
        return conn

    @pytest.mark.parametrize(
        "session_id,executor",
        (
            ("codex-idle", "codex"),
            ("codex-desktop-idle", "codex-desktop"),
            ("cursor-idle", "cursor"),
        ),
    )
    def test_empty_session_uses_base_ttl_on_every_harness(
        self, conn_with_events, session_id, executor
    ):
        conn = conn_with_events
        _register(conn, session_id=session_id, executor=executor)
        conn.execute(
            """UPDATE harness_sessions
               SET last_heartbeat = %s
               WHERE session_id = %s""",
            (_ago_minutes(25), session_id),
        )
        conn.commit()

        result = clean_stale_harness_sessions(conn, stale_threshold_minutes=20)
        assert result["total_reclaimed"] == 1

    def test_empty_session_far_past_base_ttl_is_reclaimed(self, conn_with_events):
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

    def test_claude_stale_uses_base_ttl(self, conn_with_events):
        """Claude sessions use the shared 20-minute base."""
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
        """Session with stale heartbeat but fresh events is not reclaimed."""
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
        """Reclaim emits HarnessSessionStaleReclaimed with required fields."""
        conn = conn_with_events
        _insert_claimable_items(conn, 777)
        _register(conn, session_id="stale-ev", executor="claude-code")
        conn.execute(
            """UPDATE harness_sessions
               SET last_heartbeat = %s
               WHERE session_id = 'stale-ev'""",
            (_ago_minutes(_PAST_HOLDINGS_TTL),),
        )
        conn.commit()
        claim_work(conn, session_id="stale-ev", item_id=777)
        stale_claim_ts = _ago_minutes(_PAST_HOLDINGS_TTL)
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
            c
            for c in mock_emit.call_args_list
            if c.args and c.args[0] == "HarnessSessionStaleReclaimed"
        ]
        assert len(stale_calls) == 1
        ctx = stale_calls[0].kwargs["context"]
        assert ctx["executor"] == "claude-code"
        assert "stale_minutes" in ctx
        assert "last_event_at" in ctx
        assert ctx["released_claim_count"] == 1
        assert ctx["effective_ttl_minutes"] == (
            DEFAULT_STALE_WITH_HOLDINGS_THRESHOLD_MINUTES
        )
        assert ctx["has_active_holdings"] is True


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
        """Sweep emits event even with no sessions to reclaim."""
        result = clean_stale_harness_sessions(conn)
        assert result["total_reclaimed"] == 0
        calls = [
            c
            for c in mock_emit.call_args_list
            if c[0][0] == EVENT_HARNESS_SESSION_STALE_SWEEP_COMPLETED
        ]
        assert len(calls) == 1
        ctx = calls[0][1]["context"]
        assert ctx["total_scanned"] == 0
        assert ctx["total_reclaimed"] == 0
        assert "sweep_duration_ms" in ctx
