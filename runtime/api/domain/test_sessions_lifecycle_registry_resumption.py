"""Tests: register_session reacquire path emits HarnessSessionResumed.

Covers AC-1, AC-4 (lock inheritance through resume), and verifies the
resumption marker is queryable with a single ``event_name`` predicate.
The existing ``SessionReactivatedWithReleasedClaims`` /
``SessionReactivationReacquiredClaims`` events must still emit — the
resumption marker is additive, not a replacement.

The reactivation reads/writes under test now issue native ``%s`` SQL, so
:class:`TestEmitSessionResumedFromReactivation` runs against a disposable
per-test Postgres database (the Yoke authority) instead of an in-memory
SQLite double. The pure-function and fully-mocked cases need no database.
"""

from __future__ import annotations

import contextlib
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from yoke_core.domain import db_backend
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from runtime.api.sessions_api_stale_test_helpers import apply_ddl_statements
from yoke_core.domain.sessions_lifecycle_reactivation import (
    emit_reactivated_with_released_claims,
)
from yoke_core.domain.sessions_lifecycle_resumption_emit import (
    EVENT_HARNESS_SESSION_RESUMED,
    build_claim_details,
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
    outcome TEXT,
    severity TEXT,
    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text)
);
"""

_CREATE_EVENT_REGISTRY = """
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


def _apply_resumption_schema() -> None:
    """``init_test_db`` strategy: build the session/claim/event tables.

    Applied through the backend factory against the repointed per-test
    Postgres DSN; the facade translates the SQLite-shaped fixture DDL so the
    reactivation reads and the best-effort telemetry emits both target the
    live authority.
    """
    conn = db_backend.connect()
    try:
        apply_ddl_statements(
            conn,
            _CREATE_SESSIONS,
            _CREATE_WORK_CLAIMS,
            _CREATE_EVENTS,
            _CREATE_EVENT_REGISTRY,
        )
        conn.commit()
    finally:
        conn.close()


def _insert_session(conn, session_id: str, ended: bool = False) -> None:
    conn.execute(
        "INSERT INTO harness_sessions "
        "(session_id, executor, provider, model, workspace, offered_at, last_heartbeat, ended_at) "
        "VALUES (%s, 'claude-code', 'anthropic', 'test', '/tmp', '2026-01-01T00:00:00Z', "
        "'2026-01-01T00:00:00Z', %s)",
        (session_id, "2026-01-01T01:00:00Z" if ended else None),
    )
    conn.commit()


def _insert_claim(
    conn,
    session_id: str,
    item_id: int,
    released: bool = False,
    release_reason=None,
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


class _PgResumptionTestCase(unittest.TestCase):
    """Per-test disposable Postgres DB with the resumption fixture schema."""

    def setUp(self) -> None:
        self._stack = contextlib.ExitStack()
        self._tmp_dir = tempfile.mkdtemp(prefix="yoke-test-resumption-")
        self.db_path = self._stack.enter_context(
            init_test_db(Path(self._tmp_dir), apply_schema=_apply_resumption_schema)
        )
        self.conn = connect_test_db(self.db_path)

    def tearDown(self) -> None:
        self.conn.close()
        self._stack.close()
        shutil.rmtree(self._tmp_dir, ignore_errors=True)


class TestEmitSessionResumedFromReactivation(_PgResumptionTestCase):
    """`emit_reactivated_with_released_claims` emits the resumption marker."""

    def test_emits_resumption_event_when_session_ended_claims_exist(self) -> None:
        conn = self.conn
        _insert_session(conn, "sess-resume", ended=True)
        _insert_claim(
            conn, "sess-resume", 700, released=True, release_reason="session_ended",
        )

        with mock.patch(
            "yoke_core.domain.sessions_lifecycle_resumption_emit.emit_session_resumed"
        ) as resumed:
            emit_reactivated_with_released_claims(conn, "sess-resume")

        resumed.assert_called_once()
        kwargs = resumed.call_args.kwargs
        self.assertEqual(kwargs["session_id"], "sess-resume")
        self.assertEqual(len(kwargs["released_claims"]), 1)
        self.assertEqual(kwargs["released_claims"][0]["item_id"], 700)

    def test_no_resumption_event_when_no_prior_session_ended_claims(self) -> None:
        conn = self.conn
        _insert_session(conn, "sess-fresh")

        with mock.patch(
            "yoke_core.domain.sessions_lifecycle_resumption_emit.emit_session_resumed"
        ) as resumed:
            emit_reactivated_with_released_claims(conn, "sess-fresh")

        resumed.assert_not_called()


class TestBuildClaimDetails(unittest.TestCase):
    """`build_claim_details` tags entries with episode_scope correctly."""

    def test_released_only_marks_inherited(self) -> None:
        details = build_claim_details(
            released_claims=[{"target_kind": "item", "item_id": 1}],
            reacquired_claims=[],
            conflicts=[],
        )
        self.assertEqual(len(details), 1)
        self.assertEqual(details[0]["episode_scope"], "inherited")
        self.assertEqual(details[0]["item_id"], 1)

    def test_reacquired_marks_reacquired_and_carries_new_claim_id(self) -> None:
        details = build_claim_details(
            released_claims=[{"target_kind": "item", "item_id": 2}],
            reacquired_claims=[
                {"target_kind": "item", "item_id": 2, "new_claim_id": 42},
            ],
            conflicts=[],
        )
        match = [d for d in details if d["item_id"] == 2]
        self.assertEqual(len(match), 1)
        self.assertEqual(match[0]["episode_scope"], "reacquired")
        self.assertEqual(match[0]["new_claim_id"], 42)

    def test_conflict_marks_conflict(self) -> None:
        details = build_claim_details(
            released_claims=[{"target_kind": "item", "item_id": 3}],
            reacquired_claims=[],
            conflicts=[
                {
                    "target_kind": "item",
                    "item_id": 3,
                    "holder_session_id": "other-sess",
                },
            ],
        )
        match = [d for d in details if d["item_id"] == 3]
        self.assertEqual(len(match), 1)
        self.assertEqual(match[0]["episode_scope"], "conflict")
        self.assertEqual(match[0]["holder_session_id"], "other-sess")


class TestResumptionEventEmission(unittest.TestCase):
    """Direct call to `emit_session_resumed` writes a queryable row."""

    def test_emit_writes_event_with_single_predicate_query(self) -> None:
        """AC-1: marker is queryable with a single event_name predicate."""
        from yoke_core.domain.sessions_lifecycle_resumption_emit import (
            emit_session_resumed,
        )

        captured: list = []

        def _fake_emit_event(name, **kwargs):
            captured.append((name, kwargs))

        with mock.patch(
            "yoke_core.domain.events.emit_event",
            side_effect=_fake_emit_event,
        ):
            emit_session_resumed(
                session_id="sess-marker",
                released_claims=[
                    {"target_kind": "item", "item_id": 11},
                ],
                reacquired_claims=[
                    {"target_kind": "item", "item_id": 11, "new_claim_id": 99},
                ],
                conflicts=[],
            )

        self.assertEqual(len(captured), 1)
        name, kwargs = captured[0]
        self.assertEqual(name, EVENT_HARNESS_SESSION_RESUMED)
        self.assertEqual(kwargs["event_kind"], "system")
        self.assertEqual(kwargs["event_type"], "session_lifecycle")
        self.assertEqual(kwargs["session_id"], "sess-marker")
        ctx = kwargs["context"]
        self.assertTrue(ctx["resumption"])
        self.assertEqual(ctx["prior_release_reason"], "session_ended")
        self.assertEqual(ctx["released_claim_count"], 1)
        self.assertEqual(ctx["reacquired_count"], 1)
        self.assertEqual(ctx["conflict_count"], 0)
        scopes = {d["episode_scope"] for d in ctx["claim_details"]}
        self.assertEqual(scopes, {"reacquired"})


if __name__ == "__main__":
    unittest.main()
