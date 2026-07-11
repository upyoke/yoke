"""Tests: ``events list --current-episode`` boundary filtering.

Covers AC-2, AC-10, AC-11: explicit session filter required, fail-closed
empty-set behavior when no boundary is recorded, AND-composition with
other filters, and boundary resolution against
``harness_sessions.episode_started_at`` (the events-side filtering of
telemetry rows stays; only boundary RESOLUTION reads the session
column).
"""

from __future__ import annotations

import contextlib
import tempfile
import unittest
from pathlib import Path

# Load events_crud first so the events_queries <-> events_crud circular
# import resolves the normal way (events_crud completes its module-level
# definitions, then pulls events_queries; the reverse order fails when
# events_queries reaches its events_crud import and events_crud tries
# to re-enter the partially-initialized module).
import yoke_core.domain.events_crud  # noqa: F401
from yoke_core.domain.events_queries import _build_where, cmd_list
from yoke_core.domain.schema_init_apply import execute_schema_script
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


_SCHEMA = """
CREATE TABLE projects (
    id INTEGER PRIMARY KEY,
    slug TEXT UNIQUE,
    name TEXT,
    public_item_prefix TEXT DEFAULT 'YOK'
);
INSERT INTO projects (id, slug, name, public_item_prefix)
VALUES (1, 'yoke', 'Yoke', 'YOK');
CREATE TABLE events (
    id INTEGER PRIMARY KEY,
    event_id TEXT,
    event_name TEXT NOT NULL,
    event_kind TEXT,
    event_type TEXT,
    event_outcome TEXT,
    source_type TEXT,
    session_id TEXT,
    project_id INTEGER,
    item_id TEXT,
    task_num INTEGER,
    context TEXT,
    outcome TEXT,
    severity TEXT,
    org_id TEXT,
    agent TEXT,
    service TEXT,
    actor_id INTEGER,
    environment TEXT,
    tool_name TEXT,
    tool_use_id TEXT,
    turn_id TEXT,
    duration_ms INTEGER,
    exit_code INTEGER,
    trace_id TEXT,
    parent_id TEXT,
    anomaly_flags TEXT,
    envelope TEXT,
    hook_event_name TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX idx_events_session_id ON events(session_id);
CREATE INDEX idx_events_created_at ON events(created_at);
CREATE TABLE harness_sessions (
    session_id TEXT PRIMARY KEY,
    episode_started_at TEXT
);
"""


def _apply_events_schema() -> None:
    """``apply_schema`` strategy applying the local events-only ``_SCHEMA``.

    Resolves its connection through the backend factory (the repointed
    ``YOKE_PG_DSN``) so ``init_test_db`` builds the events table in the
    per-test database ``cmd_list`` reads back from.
    """
    from yoke_core.domain import db_backend

    conn = db_backend.connect()
    try:
        execute_schema_script(conn, _SCHEMA)
        conn.commit()
    finally:
        conn.close()


@contextlib.contextmanager
def _setup_db():
    """Yield a path-shaped ``db_path`` token with ``_SCHEMA`` applied.

    ``init_test_db`` provisions a disposable per-test database and repoints
    ``YOKE_PG_DSN`` for the context's lifetime, so the raw-insert
    ``connect_test_db`` calls and the ``cmd_list`` readback share one DB.
    """
    with tempfile.TemporaryDirectory(prefix="yoke-test-") as tmp_dir:
        with init_test_db(
            Path(tmp_dir), apply_schema=_apply_events_schema
        ) as db_path:
            yield db_path


def _stamp_episode(db_path: str, session_id: str, at: str) -> None:
    """Record the episode boundary the way register_session does."""
    conn = connect_test_db(db_path)
    conn.execute(
        "INSERT INTO harness_sessions (session_id, episode_started_at) "
        "VALUES (%s, %s) "
        "ON CONFLICT(session_id) DO UPDATE SET episode_started_at = %s",
        (session_id, at, at),
    )
    conn.commit()
    conn.close()


def _insert_event(
    db_path: str,
    *,
    name: str,
    session_id: str,
    created_at: str,
    severity: str = "INFO",
    item_id: str = "",
) -> None:
    conn = connect_test_db(db_path)
    conn.execute(
        "INSERT INTO events (event_name, event_kind, event_type, source_type, "
        "session_id, project_id, item_id, severity, created_at) "
        "VALUES (%s, 'system', 'session_lifecycle', 'backend', %s, 1, %s, %s, %s)",
        (name, session_id, item_id or None, severity, created_at),
    )
    conn.commit()
    conn.close()


class TestCurrentEpisodeFlag(unittest.TestCase):

    def test_requires_explicit_session_id(self) -> None:
        with self.assertRaises(ValueError) as exc:
            _build_where(["--current-episode"])
        self.assertIn("--session-id", str(exc.exception))

    def test_returns_empty_set_when_no_boundary_recorded(self) -> None:
        with _setup_db() as db_path:
            _insert_event(
                db_path,
                name="SomethingElse",
                session_id="sess-x",
                created_at="2026-05-01T00:00:00Z",
            )
            # No harness_sessions row / no episode_started_at: fail closed.
            result = cmd_list(
                db_path,
                ["--session-id", "sess-x", "--current-episode"],
            )
            self.assertEqual(result, "")

    def test_boundary_started_only(self) -> None:
        with _setup_db() as db_path:
            _insert_event(
                db_path,
                name="UnrelatedEvent",
                session_id="sess-a",
                created_at="2026-05-01T00:00:00Z",
            )
            _insert_event(
                db_path,
                name="HarnessSessionStarted",
                session_id="sess-a",
                created_at="2026-05-02T00:00:00Z",
            )
            _insert_event(
                db_path,
                name="WorkClaimed",
                session_id="sess-a",
                created_at="2026-05-03T00:00:00Z",
            )
            _stamp_episode(db_path, "sess-a", "2026-05-02T00:00:00Z")
            result = cmd_list(
                db_path,
                ["--session-id", "sess-a", "--current-episode"],
            )
            self.assertIn("HarnessSessionStarted", result)
            self.assertIn("WorkClaimed", result)
            self.assertNotIn("UnrelatedEvent", result)

    def test_boundary_prefers_resumed_over_started(self) -> None:
        """The stamped column carries the most recent boundary moment."""
        with _setup_db() as db_path:
            _insert_event(
                db_path,
                name="HarnessSessionStarted",
                session_id="sess-b",
                created_at="2026-05-01T00:00:00Z",
            )
            _insert_event(
                db_path,
                name="WorkClaimed",
                session_id="sess-b",
                created_at="2026-05-02T00:00:00Z",
            )
            _insert_event(
                db_path,
                name="HarnessSessionResumed",
                session_id="sess-b",
                created_at="2026-05-03T00:00:00Z",
            )
            _insert_event(
                db_path,
                name="EpisodeTwoEvent",
                session_id="sess-b",
                created_at="2026-05-04T00:00:00Z",
            )
            # register_session stamped the boundary at the resume moment.
            _stamp_episode(db_path, "sess-b", "2026-05-03T00:00:00Z")
            result = cmd_list(
                db_path,
                ["--session-id", "sess-b", "--current-episode"],
            )
            self.assertIn("HarnessSessionResumed", result)
            self.assertIn("EpisodeTwoEvent", result)
            self.assertNotIn("WorkClaimed", result)

    def test_other_session_events_not_returned(self) -> None:
        with _setup_db() as db_path:
            _insert_event(
                db_path,
                name="HarnessSessionStarted",
                session_id="sess-c",
                created_at="2026-05-01T00:00:00Z",
            )
            _insert_event(
                db_path,
                name="OtherSessionEvent",
                session_id="sess-other",
                created_at="2026-05-02T00:00:00Z",
            )
            _stamp_episode(db_path, "sess-c", "2026-05-01T00:00:00Z")
            result = cmd_list(
                db_path,
                ["--session-id", "sess-c", "--current-episode"],
            )
            self.assertNotIn("OtherSessionEvent", result)

    def test_composes_with_event_name_filter(self) -> None:
        """AC-11: filter composition is AND across all predicates."""
        with _setup_db() as db_path:
            _insert_event(
                db_path,
                name="HarnessSessionStarted",
                session_id="sess-d",
                created_at="2026-05-01T00:00:00Z",
            )
            _insert_event(
                db_path,
                name="WorkClaimed",
                session_id="sess-d",
                created_at="2026-05-02T00:00:00Z",
            )
            _insert_event(
                db_path,
                name="WorkReleased",
                session_id="sess-d",
                created_at="2026-05-03T00:00:00Z",
            )
            _stamp_episode(db_path, "sess-d", "2026-05-01T00:00:00Z")
            result = cmd_list(
                db_path,
                [
                    "--session-id", "sess-d",
                    "--current-episode",
                    "--event-name", "WorkClaimed",
                ],
            )
            self.assertIn("WorkClaimed", result)
            self.assertNotIn("WorkReleased", result)
            self.assertNotIn("HarnessSessionStarted", result)


if __name__ == "__main__":
    unittest.main()
