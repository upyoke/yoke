"""Conditional auto-reacquire + conflict fall-through coverage.

Reactivation auto-reacquires session_ended claims within window.
Reactivation outside window does not auto-reacquire.
Conflict with another active session falls through to advisory.

Runs against a disposable per-test Postgres database (the Yoke
authority), not an in-memory SQLite double: the reactivation module
under test now issues native ``%s`` SQL that only the Postgres backend
parses. Each test class inherits the per-test DB lifecycle from
:class:`_PgReacquireTestCase`.
"""

from __future__ import annotations

import contextlib
import json
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from yoke_core.domain import db_backend
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from runtime.api.sessions_api_stale_test_helpers import apply_ddl_statements
from yoke_core.domain.sessions_lifecycle_reactivation import (
    auto_reacquire_session_ended_claims,
    emit_reactivated_with_released_claims,
)


_CREATE_SESSIONS = """
CREATE TABLE IF NOT EXISTS harness_sessions (
    session_id TEXT PRIMARY KEY,
    executor TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL DEFAULT '',
    execution_lane TEXT NOT NULL DEFAULT 'primary',
    capabilities TEXT,
    workspace TEXT NOT NULL DEFAULT '',
    mode TEXT NOT NULL DEFAULT 'wait',
    offered_at TEXT NOT NULL,
    last_heartbeat TEXT NOT NULL,
    ended_at TEXT,
    offer_envelope TEXT,
    actor_id INTEGER,
    last_tool_call_at TEXT,
    tool_call_count INTEGER NOT NULL DEFAULT 0,
    episode_started_at TEXT,
    pending_resume_notice TEXT
);
"""

_CREATE_WORK_CLAIMS = """
CREATE TABLE IF NOT EXISTS work_claims (
    id INTEGER PRIMARY KEY,
    session_id TEXT NOT NULL,
    target_kind TEXT NOT NULL,
    item_id INTEGER,
    epic_id INTEGER,
    task_num INTEGER,
    process_key TEXT,
    conflict_group TEXT,
    claim_type TEXT NOT NULL DEFAULT 'exclusive',
    claimed_at TEXT NOT NULL,
    last_heartbeat TEXT NOT NULL,
    released_at TEXT,
    release_reason TEXT
);
"""

_CREATE_EVENTS = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    event_name TEXT NOT NULL,
    event_kind TEXT,
    event_type TEXT,
    source_type TEXT,
    session_id TEXT,
    project_id INTEGER,
    item_id TEXT,
    task_num INTEGER,
    context TEXT,
    envelope TEXT,
    outcome TEXT,
    severity TEXT,
    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text)
);
"""


def _apply_reacquire_schema() -> None:
    """``init_test_db`` strategy: build the minimal session/claim/event tables.

    Resolves the connection through the backend factory so the fixture DDL is
    applied to the repointed per-test Postgres database; the facade translates
    the SQLite-shaped ``INTEGER PRIMARY KEY`` DDL so the same constants seed
    the live authority.
    """
    conn = db_backend.connect()
    try:
        apply_ddl_statements(conn, _CREATE_SESSIONS, _CREATE_WORK_CLAIMS, _CREATE_EVENTS)
        conn.commit()
    finally:
        conn.close()


class _PgReacquireTestCase(unittest.TestCase):
    """Per-test disposable Postgres DB with the reactivation fixture schema."""

    def setUp(self) -> None:
        self._stack = contextlib.ExitStack()
        self._tmp_dir = tempfile.mkdtemp(prefix="yoke-test-reacquire-")
        self.db_path = self._stack.enter_context(
            init_test_db(Path(self._tmp_dir), apply_schema=_apply_reacquire_schema)
        )
        self.conn = connect_test_db(self.db_path)

    def tearDown(self) -> None:
        self.conn.close()
        self._stack.close()
        shutil.rmtree(self._tmp_dir, ignore_errors=True)


def _iso(delta_s: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=delta_s)).isoformat(
        timespec="microseconds"
    ).replace("+00:00", "Z")


def _insert_session(conn, session_id: str) -> None:
    conn.execute(
        "INSERT INTO harness_sessions "
        "(session_id, executor, provider, model, workspace, offered_at, last_heartbeat) "
        "VALUES (%s, 'claude-code', 'anthropic', 'm', '/tmp', %s, %s)",
        (session_id, _iso(), _iso()),
    )
    conn.commit()


def _insert_released_claim(
    conn,
    session_id: str,
    item_id: int,
    *,
    released_age_s: int,
) -> None:
    conn.execute(
        "INSERT INTO work_claims "
        "(session_id, target_kind, item_id, claim_type, claimed_at, "
        " last_heartbeat, released_at, release_reason) "
        "VALUES (%s, 'item', %s, 'exclusive', %s, %s, %s, 'session_ended')",
        (
            session_id,
            item_id,
            _iso(-released_age_s - 30),
            _iso(-released_age_s),
            _iso(-released_age_s),
        ),
    )
    conn.commit()


def _insert_active_claim_other(
    conn, session_id: str, item_id: int,
) -> None:
    conn.execute(
        "INSERT INTO work_claims "
        "(session_id, target_kind, item_id, claim_type, claimed_at, last_heartbeat) "
        "VALUES (%s, 'item', %s, 'exclusive', %s, %s)",
        (session_id, item_id, _iso(), _iso()),
    )
    conn.commit()


class TestAutoReacquireWithinWindow(_PgReacquireTestCase):
    def test_within_window_inserts_new_active_claim(self) -> None:
        conn = self.conn
        _insert_session(conn, "sess-A")
        _insert_released_claim(conn, "sess-A", 100, released_age_s=10)
        reacquired, conflicts = auto_reacquire_session_ended_claims(
            conn, "sess-A", reacquire_window_s=300,
        )
        self.assertEqual(len(reacquired), 1)
        self.assertEqual(reacquired[0]["item_id"], 100)
        self.assertEqual(conflicts, [])
        active_count = conn.execute(
            "SELECT COUNT(*) FROM work_claims "
            "WHERE session_id = %s AND released_at IS NULL",
            ("sess-A",),
        ).fetchone()[0]
        self.assertEqual(active_count, 1)

    def test_outside_window_does_not_reacquire(self) -> None:
        conn = self.conn
        _insert_session(conn, "sess-B")
        # released 600s ago — outside default 300s window
        _insert_released_claim(conn, "sess-B", 200, released_age_s=600)
        reacquired, conflicts = auto_reacquire_session_ended_claims(
            conn, "sess-B", reacquire_window_s=300,
        )
        self.assertEqual(reacquired, [])
        self.assertEqual(conflicts, [])

    def test_conflict_with_other_session_falls_through(self) -> None:
        conn = self.conn
        _insert_session(conn, "sess-orig")
        _insert_session(conn, "sess-other")
        _insert_released_claim(conn, "sess-orig", 300, released_age_s=10)
        # Another session holds an active claim on the same item.
        _insert_active_claim_other(conn, "sess-other", 300)
        reacquired, conflicts = auto_reacquire_session_ended_claims(
            conn, "sess-orig", reacquire_window_s=300,
        )
        self.assertEqual(reacquired, [])
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["holder_session_id"], "sess-other")

    def test_multiple_recent_releases_for_same_target_reacquire_once(self) -> None:
        conn = self.conn
        _insert_session(conn, "sess-repeat")
        _insert_released_claim(conn, "sess-repeat", 301, released_age_s=20)
        _insert_released_claim(conn, "sess-repeat", 301, released_age_s=10)
        reacquired, conflicts = auto_reacquire_session_ended_claims(
            conn, "sess-repeat", reacquire_window_s=300,
        )
        self.assertEqual(len(reacquired), 1)
        self.assertEqual(conflicts, [])
        active_count = conn.execute(
            "SELECT COUNT(*) FROM work_claims "
            "WHERE session_id = %s AND item_id = %s AND released_at IS NULL",
            ("sess-repeat", 301),
        ).fetchone()[0]
        self.assertEqual(active_count, 1)


class TestEmitReactivatedWithReleasedClaimsReceipt(_PgReacquireTestCase):
    def test_emits_receipt_when_reacquire_or_conflict(self) -> None:
        conn = self.conn
        _insert_session(conn, "sess-C")
        _insert_released_claim(conn, "sess-C", 400, released_age_s=10)
        with mock.patch(
            "yoke_core.domain.events.emit_event"
        ) as emit_event, mock.patch(
            "yoke_core.domain.sessions_lifecycle_reactivation._emit_session_event"
        ):
            emit_reactivated_with_released_claims(
                conn, "sess-C", reacquire_window_s=300,
            )
        event_names = [call.args[0] for call in emit_event.call_args_list]
        self.assertIn("SessionReactivationReacquiredClaims", event_names)

    def test_no_receipt_when_nothing_to_reacquire(self) -> None:
        conn = self.conn
        _insert_session(conn, "sess-D")
        _insert_released_claim(conn, "sess-D", 500, released_age_s=99999)
        with mock.patch(
            "yoke_core.domain.events.emit_event"
        ) as emit_event, mock.patch(
            "yoke_core.domain.sessions_lifecycle_reactivation._emit_session_event"
        ):
            emit_reactivated_with_released_claims(
                conn, "sess-D", reacquire_window_s=300,
            )
        names = [call.args[0] for call in emit_event.call_args_list]
        self.assertNotIn("SessionReactivationReacquiredClaims", names)


if __name__ == "__main__":
    unittest.main()
