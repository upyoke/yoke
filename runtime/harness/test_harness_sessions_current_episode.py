"""Tests: ``who-claims --current-episode`` shows inheritance, never hides.

Covers AC-3, AC-4, AC-12: inherited claims remain visible with an
explicit ``episode_scope`` marker; reacquired claims show inheritance
fact; missing boundary still surfaces the claim row. Boundary truth is
``harness_sessions.episode_started_at`` (stamped at register/resume).
"""

from __future__ import annotations

import contextlib
import tempfile
import unittest
from pathlib import Path

from yoke_core.domain import db_backend
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from runtime.harness.harness_sessions_claims import cmd_who_claims


_SCHEMA = """
CREATE TABLE work_claims (
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
CREATE TABLE harness_sessions (
    session_id TEXT PRIMARY KEY,
    episode_started_at TEXT
);
"""


def _apply_schema() -> None:
    conn = db_backend.connect()
    try:
        apply_fixture_ddl(conn, _SCHEMA)
    finally:
        conn.close()


@contextlib.contextmanager
def _build_conn():
    with tempfile.TemporaryDirectory() as tmp:
        with init_test_db(Path(tmp), apply_schema=_apply_schema) as db_path:
            conn = connect_test_db(db_path)
            try:
                yield conn
            finally:
                conn.close()


def _insert_claim(
    conn,
    session_id: str,
    item_id: int,
    claimed_at: str,
) -> int:
    cursor = conn.execute(
        "INSERT INTO work_claims "
        "(session_id, target_kind, item_id, claim_type, claimed_at, last_heartbeat) "
        "VALUES (%s, 'item', %s, 'exclusive', %s, %s) RETURNING id",
        (session_id, item_id, claimed_at, claimed_at),
    )
    row = cursor.fetchone()
    cursor.close()
    conn.commit()
    return int(row[0])


def _stamp_episode(conn, session_id: str, at: str) -> None:
    """Record the episode boundary the way register_session does."""
    conn.execute(
        "INSERT INTO harness_sessions (session_id, episode_started_at) "
        "VALUES (%s, %s) "
        "ON CONFLICT(session_id) DO UPDATE SET episode_started_at = %s",
        (session_id, at, at),
    )
    conn.commit()


class TestWhoClaimsCurrentEpisode(unittest.TestCase):

    def test_baseline_without_flag_unchanged(self) -> None:
        with _build_conn() as conn:
            _insert_claim(conn, "sess-base", 10, "2026-05-01T00:00:00Z")
            out = cmd_who_claims(
                conn, "10", caller_session_id="sess-base",
            )
        # Baseline output (no flag) is unchanged — no episode_scope line.
        self.assertNotIn("episode_scope=", out)
        self.assertNotIn("episode_boundary=", out)

    def test_current_episode_marks_current_when_claim_after_boundary(self) -> None:
        with _build_conn() as conn:
            _stamp_episode(conn, "sess-cur", "2026-05-01T00:00:00Z")
            _insert_claim(conn, "sess-cur", 11, "2026-05-02T00:00:00Z")
            out = cmd_who_claims(
                conn, "11",
                caller_session_id="sess-cur",
                current_episode=True,
            )
        self.assertIn("episode_scope=current_episode", out)
        self.assertIn("episode_boundary=2026-05-01T00:00:00Z", out)

    def test_current_episode_marks_inherited_when_claim_predates_boundary(self) -> None:
        """AC-12: inherited claims are visible, not hidden."""
        with _build_conn() as conn:
            # Claim acquired BEFORE the most recent resume boundary;
            # the resume re-stamped episode_started_at past it.
            _insert_claim(conn, "sess-inh", 12, "2026-04-30T00:00:00Z")
            _stamp_episode(conn, "sess-inh", "2026-05-02T00:00:00Z")
            out = cmd_who_claims(
                conn, "12",
                caller_session_id="sess-inh",
                current_episode=True,
            )
        # Inheritance is visible. AC-12: it is NOT omitted.
        self.assertIn("episode_scope=inherited_from_prior_episode", out)
        self.assertIn("episode_boundary=2026-05-02T00:00:00Z", out)
        # The canonical claim row is still the first line.
        first_line = out.split("\n", 1)[0]
        self.assertIn("12", first_line)

    def test_missing_boundary_surfaces_none_marker(self) -> None:
        with _build_conn() as conn:
            _insert_claim(conn, "sess-nb", 13, "2026-05-01T00:00:00Z")
            out = cmd_who_claims(
                conn, "13",
                caller_session_id="sess-nb",
                current_episode=True,
            )
        self.assertIn("episode_scope=unknown", out)
        self.assertIn("episode_boundary=none", out)
        # Claim still surfaces — the flag does NOT hide unowned claims.
        first_line = out.split("\n", 1)[0]
        self.assertIn("13", first_line)


if __name__ == "__main__":
    unittest.main()
