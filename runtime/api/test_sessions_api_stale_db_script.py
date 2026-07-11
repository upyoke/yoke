"""TestSessionsDbScript: subprocess-driven harness_sessions CLI tests."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import pytest

from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from runtime.api.sessions_api_stale_test_helpers import apply_ddl_statements
from runtime.api.test_sessions import _REPO_ROOT
from runtime.api.test_constants import TEST_MODEL_ID


_STALE_DB_SCHEMA = """
            CREATE TABLE projects (
                id INTEGER PRIMARY KEY,
                slug TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                public_item_prefix TEXT NOT NULL DEFAULT 'YOK',
                created_at TEXT NOT NULL DEFAULT '2026-01-01T00:00:00Z'
            );
            INSERT INTO projects (id, slug, name, public_item_prefix, created_at)
            VALUES (1, 'yoke', 'Yoke', 'YOK', '2026-01-01T00:00:00Z');
            CREATE TABLE harness_sessions (
                session_id TEXT PRIMARY KEY,
                executor TEXT NOT NULL,
                executor_display_name TEXT DEFAULT NULL,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                execution_lane TEXT NOT NULL DEFAULT 'primary',
                capabilities TEXT DEFAULT '[]',
                workspace TEXT NOT NULL,
                mode TEXT DEFAULT 'wait',
                offered_at TEXT NOT NULL,
                last_heartbeat TEXT NOT NULL,
                ended_at TEXT,
                offer_envelope TEXT,
                current_item_id TEXT DEFAULT NULL,
                current_item_set_at TEXT DEFAULT NULL,
                recent_item_id TEXT DEFAULT NULL,
                recent_item_status TEXT DEFAULT NULL,
                recent_item_recorded_at TEXT DEFAULT NULL,
                actor_id INTEGER DEFAULT NULL,
                last_tool_call_at TEXT DEFAULT NULL,
                tool_call_count INTEGER NOT NULL DEFAULT 0,
                episode_started_at TEXT DEFAULT NULL,
                pending_resume_notice TEXT DEFAULT NULL
            );
            CREATE TABLE work_claims (
    id INTEGER PRIMARY KEY,
    session_id TEXT NOT NULL,
    target_kind TEXT NOT NULL CHECK(target_kind IN ('item','epic_task','process')),
    item_id INTEGER,
    epic_id INTEGER,
    task_num INTEGER,
    process_key TEXT,
    conflict_group TEXT,
    claim_type TEXT NOT NULL DEFAULT 'exclusive' CHECK(claim_type='exclusive'),
    claimed_at TEXT NOT NULL,
    last_heartbeat TEXT NOT NULL,
    released_at TEXT,
    release_reason TEXT CHECK(release_reason IS NULL OR release_reason IN ('completed','released','reclaimed','handed_off','expired','session_ended')),
    CHECK (
      (target_kind='item' AND item_id IS NOT NULL AND epic_id IS NULL AND task_num IS NULL AND process_key IS NULL AND conflict_group IS NULL) OR
      (target_kind='epic_task' AND item_id IS NULL AND epic_id IS NOT NULL AND task_num IS NOT NULL AND process_key IS NULL AND conflict_group IS NULL) OR
      (target_kind='process' AND item_id IS NULL AND epic_id IS NULL AND task_num IS NULL AND process_key IS NOT NULL AND conflict_group IS NOT NULL)
    ),
    FOREIGN KEY (session_id) REFERENCES harness_sessions(session_id)
);
            CREATE TABLE events (
                id INTEGER PRIMARY KEY,
                event_id TEXT NOT NULL UNIQUE,
                source_type TEXT NOT NULL,
                session_id TEXT NOT NULL,
                severity TEXT NOT NULL DEFAULT 'INFO',
                event_kind TEXT NOT NULL,
                event_type TEXT NOT NULL,
                event_name TEXT NOT NULL,
                event_outcome TEXT,
                org_id TEXT,
                actor_id INTEGER,
                environment TEXT,
                service TEXT NOT NULL DEFAULT 'cli',
                project_id INTEGER DEFAULT 1,
                item_id TEXT,
                task_num INTEGER,
                agent TEXT,
                tool_name TEXT,
                duration_ms INTEGER,
                exit_code INTEGER,
                trace_id TEXT,
                parent_id TEXT,
                anomaly_flags TEXT,
                tool_use_id TEXT,
                turn_id TEXT,
                hook_event_name TEXT,
                envelope TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS event_registry (
                event_name TEXT PRIMARY KEY,
                owner_service TEXT,
                status TEXT
            );
"""


def _apply_stale_db_schema() -> None:
    """``init_test_db`` applier: build the bespoke session/claim/events schema.

    Resolves its connection through the backend factory so the same DDL builds
    on the per-test SQLite file or the repointed per-test Postgres DB. The
    empty ``event_registry`` table lets the native event emitter's retired-name
    guard run without poisoning the transaction.
    """
    from yoke_core.domain import db_backend

    conn = db_backend.connect()
    try:
        apply_ddl_statements(conn, _STALE_DB_SCHEMA)
        conn.commit()
    finally:
        conn.close()


class TestSessionsDbScript:
    @pytest.fixture
    def db_path(self, tmp_path):
        # Per-test DB on both engines via init_test_db (SQLite file under
        # tmp_path; disposable per-test Postgres DB with YOKE_PG_DSN repointed
        # for the context). The yield keeps the context open so the subprocess
        # CLI calls (which os.environ.copy() the repointed DSN) and the in-test
        # readback connections all hit this per-test DB instead of colliding on
        # the shared ambient Postgres DB under ``-n``.
        with init_test_db(tmp_path, apply_schema=_apply_stale_db_schema) as path:
            yield path

    def _run_script(self, db_path, *args: str) -> subprocess.CompletedProcess[str]:
        """Invoke the Python harness_sessions owner with *args*.

        replaces the retired ``harness-sessions-db.sh`` shell
        entrypoint with a direct module invocation.
        """
        env = os.environ.copy()
        env["YOKE_DB"] = str(db_path)
        return subprocess.run(
            [sys.executable, "-m", "runtime.harness.harness_sessions", *args],
            env=env,
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
        )

    def test_duplicate_claim_by_same_session_is_idempotent(self, db_path):
        """Idempotent self-claim: re-claiming same item by same session succeeds."""
        first = self._run_script(
            db_path,
            "begin",
            "sess-1",
            "DARIUS",
            "anthropic",
            TEST_MODEL_ID,
            "/tmp/work",
        )
        assert first.returncode == 0
        claim = self._run_script(db_path, "claim", "sess-1", "--target-kind", "item", "--item-id", "9999")
        assert claim.returncode == 0

        duplicate = self._run_script(db_path, "claim", "sess-1", "--target-kind", "item", "--item-id", "9999")

        assert duplicate.returncode == 0
        assert "already owned" in duplicate.stdout

    def test_ended_session_cannot_claim_new_work(self, db_path):
        register = self._run_script(
            db_path,
            "begin",
            "sess-1",
            "DARIUS",
            "anthropic",
            TEST_MODEL_ID,
            "/tmp/work",
        )
        assert register.returncode == 0
        end = self._run_script(db_path, "end", "sess-1")
        assert end.returncode == 0

        claim = self._run_script(db_path, "claim", "sess-1", "--target-kind", "item", "--item-id", "99")

        assert claim.returncode != 0
        assert "already ended" in claim.stderr

    def test_releasing_missing_claim_fails(self, db_path):
        release = self._run_script(db_path, "release", "9999")

        assert release.returncode != 0
        assert "not found" in release.stderr

    def test_stale_uses_iso_heartbeat_comparison(self, db_path):
        register = self._run_script(
            db_path,
            "begin",
            "sess-1",
            "DARIUS",
            "anthropic",
            TEST_MODEL_ID,
            "/tmp/work",
        )
        assert register.returncode == 0

        stale_iso = (datetime.now(timezone.utc) - timedelta(minutes=30)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        conn = connect_test_db(db_path)
        conn.execute(
            "UPDATE harness_sessions SET last_heartbeat = %s WHERE session_id='sess-1'",
            (stale_iso,),
        )
        # Backdate events so multi-signal stale detection sees no recent activity
        conn.execute(
            "UPDATE events SET created_at = %s WHERE session_id='sess-1'",
            (stale_iso,),
        )
        conn.commit()
        conn.close()

        stale = self._run_script(db_path, "stale", "10")
        assert stale.returncode == 0
        assert "sess-1" in stale.stdout

    def test_stale_excludes_sessions_with_active_claims(self, db_path):
        """A session holding an active work claim is never stale."""
        self._run_script(db_path, "begin", "sess-1", "DARIUS",
                         "anthropic", TEST_MODEL_ID, "/tmp/work")

        # Claim an item so the session holds an active claim
        self._run_script(db_path, "claim", "sess-1", "--target-kind", "item", "--item-id", "99")

        stale_iso = (datetime.now(timezone.utc) - timedelta(minutes=120)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        conn = connect_test_db(db_path)
        conn.execute(
            "UPDATE harness_sessions SET last_heartbeat = %s WHERE session_id='sess-1'",
            (stale_iso,),
        )
        conn.execute(
            "UPDATE events SET created_at = %s WHERE session_id='sess-1'",
            (stale_iso,),
        )
        conn.commit()
        conn.close()

        # Even with a very low threshold, the active claim protects the session
        stale = self._run_script(db_path, "stale", "10")
        assert stale.returncode == 0
        assert "sess-1" not in stale.stdout

    def test_stale_excludes_sessions_with_recent_tool_activity(self, db_path):
        """Recent tool activity keeps a session non-stale despite old heartbeat."""
        self._run_script(db_path, "begin", "sess-1", "DARIUS",
                         "anthropic", TEST_MODEL_ID, "/tmp/work")

        stale_iso = (datetime.now(timezone.utc) - timedelta(minutes=120)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        fresh_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        conn = connect_test_db(db_path)
        conn.execute(
            "UPDATE harness_sessions SET last_heartbeat = %s, "
            "last_tool_call_at = %s, tool_call_count = 1 "
            "WHERE session_id='sess-1'",
            (stale_iso, fresh_iso),
        )
        conn.commit()
        conn.close()

        stale = self._run_script(db_path, "stale", "10")
        assert stale.returncode == 0
        assert "sess-1" not in stale.stdout
