"""Regression tests: session-end + reactivation + conduct re-entry claim gap.

Simulate the silent-no-claim window that motivated this ticket:
  1. Session is created and claims an item.
  2. Session is ended — claim is released with reason='session_ended'.
  3. Same session is reactivated (ended_at cleared).
  4. Advisory event is emitted but no new work_claims row is inserted.
  5. Caller must explicitly re-run claim-work to hold an active claim.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock
from typing import Any, Dict, Optional

from yoke_core.domain.sessions_analytics_core import (
    EVENT_SESSION_REACTIVATED_WITH_RELEASED_CLAIMS,
)
from yoke_core.domain.sessions_lifecycle_reactivation import (
    emit_reactivated_with_released_claims,
)
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl


# ---------------------------------------------------------------------------
# Minimal schema fixture
# ---------------------------------------------------------------------------

_CREATE_PROJECTS = """
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY,
    slug TEXT UNIQUE,
    name TEXT DEFAULT '',
    emoji TEXT DEFAULT '',
    public_item_prefix TEXT DEFAULT 'YOK'
);
INSERT INTO projects (id, slug, name, emoji, public_item_prefix)
VALUES (1, 'yoke', 'Yoke', '', 'YOK');
"""

_CREATE_SESSIONS = """
CREATE TABLE IF NOT EXISTS harness_sessions (
    session_id TEXT PRIMARY KEY, executor TEXT NOT NULL,
    executor_display_name TEXT DEFAULT NULL, provider TEXT NOT NULL,
    model TEXT NOT NULL DEFAULT '', execution_lane TEXT NOT NULL DEFAULT 'primary',
    capabilities TEXT, workspace TEXT NOT NULL DEFAULT '',
    project_id INTEGER NOT NULL,
    mode TEXT NOT NULL DEFAULT 'wait', offered_at TEXT NOT NULL,
    last_heartbeat TEXT NOT NULL, ended_at TEXT, offer_envelope TEXT,
    actor_id INTEGER, last_tool_call_at TEXT,
    tool_call_count INTEGER NOT NULL DEFAULT 0,
    episode_started_at TEXT, pending_resume_notice TEXT
);
"""

_CREATE_WORK_CLAIMS = """
CREATE TABLE IF NOT EXISTS work_claims (
    id INTEGER PRIMARY KEY, session_id TEXT NOT NULL, target_kind TEXT NOT NULL,
    item_id INTEGER, epic_id INTEGER, task_num INTEGER, process_key TEXT,
    conflict_group TEXT, claim_type TEXT NOT NULL DEFAULT 'exclusive',
    claimed_at TEXT NOT NULL, last_heartbeat TEXT NOT NULL,
    released_at TEXT, release_reason TEXT
);
"""

_CREATE_EVENTS = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY, event_name TEXT NOT NULL, event_kind TEXT,
    event_type TEXT, source_type TEXT, session_id TEXT, project_id INTEGER,
    item_id TEXT, task_num INTEGER, context TEXT, outcome TEXT, severity TEXT,
    created_at TEXT NOT NULL
);
"""

_CREATE_EVENT_REGISTRY = """
CREATE TABLE IF NOT EXISTS event_registry (
    event_name TEXT PRIMARY KEY, event_kind TEXT, event_type TEXT,
    owner_service TEXT, description TEXT, context_schema TEXT,
    severity_default TEXT, added_in TEXT, status TEXT DEFAULT 'active'
);
"""

# register_session's actor resolver runs `SELECT 1 FROM actors WHERE id = %s`
# when callers pass an explicit actor_id. An empty actors table lets that probe
# succeed cleanly; without it the missing-relation error aborts the transaction
# before the subsequent INSERT.
_CREATE_ACTORS = """
CREATE TABLE IF NOT EXISTS actors (id INTEGER PRIMARY KEY);
"""


def _apply_reactivation_schema() -> None:
    """``apply_schema`` strategy building the fixture via the backend factory.

    ``register_session`` resolves its expected-exception type from
    ``db_backend``, so the seeding connection MUST be backend-resolved; a raw
    in-memory DB raises a different integrity exception than the Postgres
    default catches.
    """
    from yoke_core.domain import db_backend

    conn = db_backend.connect()
    try:
        apply_fixture_ddl(
            conn,
            _CREATE_PROJECTS + _CREATE_SESSIONS + _CREATE_WORK_CLAIMS + _CREATE_EVENTS
            + _CREATE_EVENT_REGISTRY + _CREATE_ACTORS,
        )
    finally:
        conn.close()


def _insert_session(conn: Any, session_id: str, ended: bool = False) -> None:
    conn.execute(
        "INSERT INTO harness_sessions "
        "(session_id, executor, provider, model, workspace, project_id, offered_at, "
        "last_heartbeat, ended_at) "
        "VALUES (%s, 'claude-code', 'anthropic', 'test', '/tmp', 1, "
        "'2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', %s)",
        (session_id, "2026-01-01T01:00:00Z" if ended else None),
    )
    conn.commit()


def _insert_claim(
    conn: Any,
    session_id: str,
    item_id: int,
    released: bool = False,
    release_reason: Optional[str] = None,
) -> int:
    cursor = conn.execute(
        "INSERT INTO work_claims "
        "(session_id, target_kind, item_id, claim_type, claimed_at, last_heartbeat, "
        " released_at, release_reason) "
        "VALUES (%s, 'item', %s, 'exclusive', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', "
        "%s, %s) RETURNING id",
        (
            session_id,
            item_id,
            "2026-01-01T01:00:00Z" if released else None,
            release_reason if released else None,
        ),
    )
    row = cursor.fetchone()
    cursor.close()
    conn.commit()
    return int(row[0])


def _emitted_events(conn: Any, event_name: str) -> list:
    rows = conn.execute(
        "SELECT * FROM events WHERE event_name = %s", (event_name,)
    ).fetchall()
    return [dict(r) for r in rows]


class _ReactivationDBTest(unittest.TestCase):
    """Per-test backend-resolved DB shared by seeding and code-under-test.

    SQLite: a real file under a temp dir. Postgres: a disposable per-test DB
    (DSN repointed for the test, dropped on teardown). Seeding and
    ``register_session`` share one connection so the backend-resolved exception
    types match the live engine.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._db_ctx = init_test_db(
            Path(self._tmp.name), apply_schema=_apply_reactivation_schema
        )
        self.db_path = self._db_ctx.__enter__()
        self.conn = connect_test_db(self.db_path)

    def tearDown(self) -> None:
        self.conn.close()
        self._db_ctx.__exit__(None, None, None)
        self._tmp.cleanup()


class TestEmitReactivatedWithReleasedClaims(_ReactivationDBTest):

    def test_no_event_when_no_session_ended_claims(self) -> None:
        """No advisory event when all claims are active or have other release reasons."""
        conn = self.conn
        _insert_session(conn, "sess-1")
        # Active claim (not released)
        _insert_claim(conn, "sess-1", 100, released=False)
        # Released for a different reason
        _insert_claim(conn, "sess-1", 101, released=True, release_reason="completed")

        with mock.patch(
            "yoke_core.domain.sessions_lifecycle_reactivation._emit_session_event"
        ) as emit_event:
            result = emit_reactivated_with_released_claims(conn, "sess-1")

        self.assertEqual(result, [])
        emit_event.assert_not_called()
        self.assertEqual(_emitted_events(conn, EVENT_SESSION_REACTIVATED_WITH_RELEASED_CLAIMS), [])

    def test_emits_event_for_session_ended_claims(self) -> None:
        """Advisory event triggered when prior session-ended claims exist."""
        conn = self.conn
        _insert_session(conn, "sess-2", ended=True)
        _insert_claim(conn, "sess-2", 200, released=True, release_reason="session_ended")

        with mock.patch(
            "yoke_core.domain.sessions_lifecycle_reactivation._emit_session_event"
        ) as emit_event:
            result = emit_reactivated_with_released_claims(conn, "sess-2")

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["target_kind"], "item")
        self.assertEqual(result[0]["item_id"], 200)
        emit_event.assert_called_once()
        event_name = emit_event.call_args.args[0]
        event_kwargs = emit_event.call_args.kwargs
        self.assertEqual(event_name, EVENT_SESSION_REACTIVATED_WITH_RELEASED_CLAIMS)
        self.assertEqual(event_kwargs["session_id"], "sess-2")
        self.assertEqual(event_kwargs["context"]["released_claim_count"], 1)
        self.assertEqual(
            event_kwargs["context"]["released_claims"],
            [{"target_kind": "item", "item_id": 200}],
        )

    def test_does_not_insert_new_work_claim(self) -> None:
        """Reactivation advisory must not auto-reacquire — no new work_claims row."""
        conn = self.conn
        _insert_session(conn, "sess-3", ended=True)
        _insert_claim(conn, "sess-3", 300, released=True, release_reason="session_ended")

        before = conn.execute(
            "SELECT COUNT(*) FROM work_claims WHERE session_id = 'sess-3'"
        ).fetchone()[0]

        with mock.patch(
            "yoke_core.domain.sessions_lifecycle_reactivation._emit_session_event"
        ):
            emit_reactivated_with_released_claims(conn, "sess-3")

        after = conn.execute(
            "SELECT COUNT(*) FROM work_claims WHERE session_id = 'sess-3'"
        ).fetchone()[0]

        self.assertEqual(before, after, "No new work_claims row should be inserted by reactivation advisory")

    def test_multiple_session_ended_claims_all_reported(self) -> None:
        """All prior session-ended claims appear in the event payload."""
        conn = self.conn
        _insert_session(conn, "sess-4", ended=True)
        _insert_claim(conn, "sess-4", 401, released=True, release_reason="session_ended")
        _insert_claim(conn, "sess-4", 402, released=True, release_reason="session_ended")

        with mock.patch(
            "yoke_core.domain.sessions_lifecycle_reactivation._emit_session_event"
        ) as emit_event:
            result = emit_reactivated_with_released_claims(conn, "sess-4")

        self.assertEqual(len(result), 2)
        item_ids = {r["item_id"] for r in result}
        self.assertEqual(item_ids, {401, 402})
        emit_event.assert_called_once()
        claims = emit_event.call_args.kwargs["context"]["released_claims"]
        self.assertEqual({claim["item_id"] for claim in claims}, {401, 402})

    def test_active_claim_not_included_in_advisory(self) -> None:
        """Active claim is not listed in reactivation advisory."""
        conn = self.conn
        _insert_session(conn, "sess-5", ended=True)
        _insert_claim(conn, "sess-5", 500, released=True, release_reason="session_ended")
        # This claim is still active (reactivation may have already occurred earlier)
        _insert_claim(conn, "sess-5", 501, released=False)

        with mock.patch(
            "yoke_core.domain.sessions_lifecycle_reactivation._emit_session_event"
        ) as emit_event:
            result = emit_reactivated_with_released_claims(conn, "sess-5")

        item_ids = {r["item_id"] for r in result}
        self.assertIn(500, item_ids)
        self.assertNotIn(501, item_ids)
        emit_event.assert_called_once()
        claims = emit_event.call_args.kwargs["context"]["released_claims"]
        self.assertEqual([claim["item_id"] for claim in claims], [500])


class TestRegisterSessionReactivationWiring(_ReactivationDBTest):
    """Integration: register_session emits advisory on reactivation."""

    def test_reactivation_calls_advisory_helper(self) -> None:
        """register_session calls emit_reactivated_with_released_claims on reactivation.

        The helper returns the released claims list — non-empty confirms the
        reactivation path fired.  (The native event emitter writes to the global
        canonical DB, so we verify via the helper's return contract rather than
        checking the in-memory test DB's events table.)
        """
        from yoke_core.domain.sessions_lifecycle_registry import register_session

        conn = self.conn
        _insert_session(conn, "sess-reac", ended=True)
        _insert_claim(conn, "sess-reac", 999, released=True, release_reason="session_ended")

        with mock.patch(
            "yoke_core.domain.sessions_lifecycle_registry.emit_reactivated_with_released_claims",
            return_value=[{"target_kind": "item", "item_id": 999}],
        ) as advisory:
            # register_session must not raise on reactivation
            register_session(
                conn,
                session_id="sess-reac",
                executor="claude-code",
                provider="anthropic",
                model="claude-sonnet-4-6",
                workspace="/tmp",
                project_id=1,
            )
        advisory.assert_called_once()
        self.assertIs(advisory.call_args.args[0], conn)
        self.assertEqual(advisory.call_args.args[1], "sess-reac")
        # If we reach here without exception, the reactivation path ran cleanly

    def test_fresh_session_no_released_claims(self) -> None:
        """Fresh session has no prior session-ended claims — helper returns empty list."""
        conn = self.conn
        _insert_session(conn, "sess-fresh")

        with mock.patch(
            "yoke_core.domain.sessions_lifecycle_reactivation._emit_session_event"
        ) as emit_event:
            result = emit_reactivated_with_released_claims(conn, "sess-fresh")
        self.assertEqual(result, [], "Fresh session must not return any released claims")
        emit_event.assert_not_called()

    def test_fresh_registration_does_not_call_advisory_helper(self) -> None:
        """Only same-session reactivation calls the released-claims advisory helper."""
        from yoke_core.domain.sessions_lifecycle_registry import register_session

        conn = self.conn

        with mock.patch(
            "yoke_core.domain.sessions_lifecycle_registry.emit_reactivated_with_released_claims"
        ) as advisory:
            register_session(
                conn,
                session_id="sess-new",
                executor="claude-code",
                provider="anthropic",
                model="claude-sonnet-4-6",
                workspace="/tmp",
                project_id=1,
            )
        advisory.assert_not_called()


if __name__ == "__main__":
    unittest.main()
