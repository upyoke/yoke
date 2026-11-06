"""Shared roster schemas and row builders for session display tests."""

from datetime import datetime, timezone
import sqlite3
from runtime.api.domain.session_roster_test_support import add_launch_read_schema


NOW = datetime(2026, 8, 22, 12, 1, tzinfo=timezone.utc)


def _connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE harness_sessions (
            session_id TEXT PRIMARY KEY,
            project_id INTEGER, org_id INTEGER, actor_id INTEGER,
            executor_surface TEXT, executor_version TEXT,
            machine_id TEXT,
            last_heartbeat TEXT,
            last_tool_call_at TEXT,
            ended_at TEXT,
            terminated_at TEXT,
            turn_posture TEXT,
            turn_posture_at TEXT,
            offer_envelope TEXT, model TEXT, requested_model TEXT
        );
        CREATE TABLE session_relays (
            relay_id TEXT PRIMARY KEY,
            machine_id TEXT,
            hostname TEXT,
            last_seen_at TEXT,
            connected_until TEXT,
            state TEXT,
            surface_versions TEXT,
            project_checkouts TEXT, actor_id INTEGER
        );
        CREATE TABLE work_claims (
            id INTEGER PRIMARY KEY,
            session_id TEXT,
            target_kind TEXT,
            scope TEXT,
            claimed_at TEXT,
            released_at TEXT
        );
        CREATE TABLE epic_tasks (
            epic_id INTEGER,
            task_num INTEGER,
            item_worktree_id INTEGER
        );
        CREATE TABLE item_worktrees (
            id INTEGER PRIMARY KEY,
            item_id INTEGER,
            path TEXT,
            branch TEXT,
            state TEXT,
            lane_role TEXT
        );
        CREATE TABLE session_message_attempts (
            attempt_id TEXT PRIMARY KEY,
            target_session_id TEXT,
            result_code TEXT,
            started_at TEXT,
            completed_at TEXT
        );
        """
    )
    add_launch_read_schema(conn)
    return conn


def _add_session(
    conn: sqlite3.Connection,
    *,
    surface: str,
    version: str,
    posture: str = "running",
    project_id: int = 10,
) -> None:
    conn.execute(
        "INSERT INTO harness_sessions (session_id, project_id, executor_surface, executor_version, machine_id, last_heartbeat, last_tool_call_at, ended_at, terminated_at, turn_posture, turn_posture_at, offer_envelope, model, requested_model) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "session-1",
            project_id,
            surface,
            version,
            "machine-1",
            "2026-08-22T12:00:00Z",
            "2026-08-22T12:00:00Z",
            None,
            None,
            posture,
            "2026-08-22T12:00:00Z",
            None,
            None,
            None,
        ),
    )


def _base_row(*, surface: str, liveness: str) -> dict[str, object]:
    return {
        "session_id": "session-1",
        "project": "yoke",
        "claims": [],
        "executor": surface.split("-", 1)[0],
        "executor_surface": surface,
        "liveness": liveness,
    }
