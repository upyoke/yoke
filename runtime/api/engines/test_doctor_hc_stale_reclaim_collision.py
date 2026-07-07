"""Doctor HC regression for HC-stale-reclaim-collision.

The check is the operator-facing observability surface for matching-shape
collisions (a ``WorkReclaimed`` event whose original session emits more
tool-call activity inside the staleness window after the reclaim
timestamp).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import List

from yoke_core.engines.doctor_hc_agents_sessions import (
    hc_stale_reclaim_collision,
)
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl


def _ago_minutes(n: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=n)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


@dataclass
class _RecordCapture:
    rows: List[tuple] = field(default_factory=list)

    def record(self, slug: str, label: str, status: str, detail: str) -> None:
        self.rows.append((slug, label, status, detail))


@dataclass
class _Args:
    pass


_MAKE_CONN_DDL = """
    CREATE TABLE harness_sessions (
        session_id TEXT PRIMARY KEY,
        executor TEXT NOT NULL DEFAULT 'claude-code'
    );
    CREATE TABLE events (
        id INTEGER PRIMARY KEY,
        event_name TEXT NOT NULL,
        event_type TEXT NOT NULL DEFAULT 'system',
        session_id TEXT,
        created_at TEXT NOT NULL,
        envelope TEXT
    );
"""


def _make_conn():
    """Disposable per-call Postgres test DB for the stale-reclaim-collision HC.

    ``YOKE_PG_DSN`` is repointed for the connection's lifetime; the returned
    connection's ``close()`` restores the prior DSN and drops the database.
    The HC under test emits dialect-aware ``now_sql`` / ``json_get`` SQL keyed
    on the resolved backend, so the connection must match the active dialect.
    """
    from yoke_core.domain import db_backend

    from runtime.api.fixtures import pg_testdb

    name = pg_testdb.create_test_database()
    new_dsn = pg_testdb.dsn_for_test_database(name)
    prior = os.environ.get(db_backend.PG_DSN_ENV)
    os.environ[db_backend.PG_DSN_ENV] = new_dsn
    conn = db_backend.connect()
    apply_fixture_ddl(conn, _MAKE_CONN_DDL)

    _base_close = conn.close

    def _close_and_drop():
        _base_close()
        if prior is not None:
            os.environ[db_backend.PG_DSN_ENV] = prior
        else:
            os.environ.pop(db_backend.PG_DSN_ENV, None)
        pg_testdb.drop_test_database(name)

    conn.close = _close_and_drop
    return conn


def _insert_session(conn, sid: str, executor: str = "claude-code") -> None:
    conn.execute(
        "INSERT INTO harness_sessions (session_id, executor) VALUES (%s, %s)",
        (sid, executor),
    )
    conn.commit()


def _insert_reclaimed_event(
    conn, sid: str, *, reclaimed_at: str, claim_id: int = 999,
) -> None:
    envelope = {
        "session_id": sid,
        "context": {"detail": {"claim_id": claim_id}},
    }
    conn.execute(
        """INSERT INTO events
           (event_name, event_type, session_id, created_at, envelope)
           VALUES ('WorkReclaimed', 'system', %s, %s, %s)""",
        (sid, reclaimed_at, json.dumps(envelope)),
    )
    conn.commit()


def _insert_tool_event(conn, sid: str, *, created_at: str) -> None:
    conn.execute(
        """INSERT INTO events
           (event_name, event_type, session_id, created_at, envelope)
           VALUES ('HarnessToolCallCompleted', 'system', %s, %s, %s)""",
        (sid, created_at, json.dumps({"session_id": sid})),
    )
    conn.commit()


class TestHcStaleReclaimCollision:
    def test_quiet_when_no_reclaims(self):
        conn = _make_conn()
        rec = _RecordCapture()
        hc_stale_reclaim_collision(conn, _Args(), rec)
        assert rec.rows == [
            ("HC-stale-reclaim-collision",
             "Silent two-session reclaim collisions",
             "PASS", ""),
        ]

    def test_quiet_when_reclaim_has_no_post_activity(self):
        conn = _make_conn()
        _insert_session(conn, "sess-A")
        # WorkReclaimed at 5 minutes ago, no tool activity afterwards.
        _insert_reclaimed_event(conn, "sess-A", reclaimed_at=_ago_minutes(5))

        rec = _RecordCapture()
        hc_stale_reclaim_collision(conn, _Args(), rec)
        assert rec.rows[0][2] == "PASS"

    def test_warn_on_post_reclaim_activity_inside_window(self):
        conn = _make_conn()
        _insert_session(conn, "sess-A", executor="claude-code")
        # Reclaim 10 minutes ago.
        _insert_reclaimed_event(
            conn, "sess-A", reclaimed_at=_ago_minutes(10), claim_id=42,
        )
        # Tool event 5 minutes ago — inside the 20-minute claude-code window.
        _insert_tool_event(conn, "sess-A", created_at=_ago_minutes(5))

        rec = _RecordCapture()
        hc_stale_reclaim_collision(conn, _Args(), rec)

        slug, label, status, detail = rec.rows[0]
        assert slug == "HC-stale-reclaim-collision"
        assert status == "WARN"
        assert "sess-A" in detail
        assert "claim=42" in detail
        assert "executor=claude-code" in detail

    def test_quiet_when_post_activity_falls_outside_window(self):
        """Activity that falls *outside* the staleness window after reclaim
        is not a collision; the reclaim ran in steady state."""
        conn = _make_conn()
        _insert_session(conn, "sess-A")
        # Reclaim 25 hours ago — outside the 24-hour look-back window.
        _insert_reclaimed_event(conn, "sess-A", reclaimed_at=_ago_minutes(25 * 60))
        _insert_tool_event(conn, "sess-A", created_at=_ago_minutes(25 * 60 - 5))

        rec = _RecordCapture()
        hc_stale_reclaim_collision(conn, _Args(), rec)
        assert rec.rows[0][2] == "PASS"

    def test_codex_uses_60_minute_window(self):
        conn = _make_conn()
        _insert_session(conn, "sess-A", executor="codex")
        # Reclaim 30 minutes ago.
        _insert_reclaimed_event(conn, "sess-A", reclaimed_at=_ago_minutes(30))
        # Tool event 10 minutes ago — inside the codex 60m window.
        _insert_tool_event(conn, "sess-A", created_at=_ago_minutes(10))

        rec = _RecordCapture()
        hc_stale_reclaim_collision(conn, _Args(), rec)

        status, detail = rec.rows[0][2], rec.rows[0][3]
        assert status == "WARN"
        assert "executor=codex" in detail
