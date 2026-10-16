"""Current launch-read schema for isolated SQLite roster fixtures."""

from __future__ import annotations

import sqlite3


def add_launch_read_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        ALTER TABLE harness_sessions ADD COLUMN workspace TEXT;
        ALTER TABLE harness_sessions ADD COLUMN offered_at TEXT;
        ALTER TABLE harness_sessions ADD COLUMN episode_started_at TEXT;
        CREATE TABLE session_launches (
            launch_id TEXT PRIMARY KEY, state TEXT, project_id INTEGER,
            selected_surface TEXT, assigned_machine_id TEXT,
            native_session_id TEXT, registered_session_id TEXT, deadline_at TEXT
        );
        CREATE TABLE session_launch_attempts (
            attempt_id TEXT PRIMARY KEY, launch_id TEXT, attempt_number INTEGER,
            started_at TEXT, evidence TEXT
        );
        """
    )
