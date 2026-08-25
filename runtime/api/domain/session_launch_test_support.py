"""SQLite fixtures for focused session-launch state-machine tests."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from yoke_core.domain.session_control_schema import create_session_control_tables
from yoke_core.domain.session_launch_requests import create_launch
from yoke_core.domain.session_launch_types import LaunchAuthorization, LaunchRequest


NOW = "2026-08-22T12:00:00Z"


def launch_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(
        """
        CREATE TABLE actors (id INTEGER PRIMARY KEY);
        CREATE TABLE projects (
            id INTEGER PRIMARY KEY,
            slug TEXT NOT NULL UNIQUE
        );
        CREATE TABLE harness_sessions (
            session_id TEXT PRIMARY KEY,
            project_id INTEGER NOT NULL,
            executor_surface TEXT,
            executor_version TEXT,
            machine_id TEXT,
            model TEXT
        );
        INSERT INTO actors (id) VALUES (1), (2), (3);
        INSERT INTO projects (id, slug) VALUES (10, 'launch-project');
        INSERT INTO harness_sessions (
            session_id, project_id, executor_surface, executor_version,
            machine_id, model
        ) VALUES ('caller', 10, 'codex-desktop', '26.814.41407', 'm0', 'gpt-5');
        """
    )
    create_session_control_tables(conn)
    conn.commit()
    return conn


def relay_connection(
    org_settings: dict[str, Any] | None = None,
) -> sqlite3.Connection:
    """Launch fixture widened with the session columns relay claiming reads."""
    conn = launch_connection()
    conn.execute("ALTER TABLE projects ADD COLUMN org_id INTEGER DEFAULT 1")
    conn.execute("CREATE TABLE organizations (id INTEGER PRIMARY KEY, settings TEXT)")
    conn.execute(
        "INSERT INTO organizations VALUES (1, ?)",
        (json.dumps(org_settings or {}),),
    )
    conn.execute(
        "ALTER TABLE harness_sessions ADD COLUMN executor TEXT DEFAULT 'codex'"
    )
    conn.execute("ALTER TABLE harness_sessions ADD COLUMN execution_lane TEXT")
    conn.execute("ALTER TABLE harness_sessions ADD COLUMN last_heartbeat TEXT")
    conn.execute("ALTER TABLE harness_sessions ADD COLUMN offered_at TEXT")
    conn.execute("ALTER TABLE harness_sessions ADD COLUMN ended_at TEXT")
    conn.execute("ALTER TABLE harness_sessions ADD COLUMN last_tool_call_at TEXT")
    conn.execute(
        "ALTER TABLE harness_sessions ADD COLUMN turn_posture TEXT "
        "NOT NULL DEFAULT 'unknown'"
    )
    conn.execute("ALTER TABLE harness_sessions ADD COLUMN turn_posture_at TEXT")
    conn.commit()
    return conn


def authorization(
    actor_id: int = 1,
    *,
    operator: bool = True,
    admin: bool = False,
) -> LaunchAuthorization:
    return LaunchAuthorization(
        actor_id=actor_id,
        session_id="caller",
        can_operate_project=operator,
        can_administer_project=admin,
    )


def add_relay(
    conn: sqlite3.Connection,
    *,
    relay_id: str = "relay-1",
    machine_id: str = "machine-1",
    surface: str = "codex-cli",
    version: str = "0.148.0a15",
    last_seen_at: str = NOW,
    connected_until: str = "2026-08-22T12:20:00Z",
    projects: list[Any] | None = None,
    actor_id: int = 1,
    hostname: str = "relay-host",
) -> None:
    conn.execute(
        "INSERT INTO session_relays "
        "(relay_id, actor_id, machine_id, hostname, surface_versions, "
        "project_checkouts, first_seen_at, last_seen_at, connected_until, state) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')",
        (
            relay_id,
            actor_id,
            machine_id,
            hostname,
            json.dumps({surface: version}),
            json.dumps(projects or [10]),
            NOW,
            last_seen_at,
            connected_until,
        ),
    )
    conn.commit()


def assigned_launch(
    conn: sqlite3.Connection,
    *,
    instructions: str = "Inspect the current work and report evidence.",
    key: str = "launch-key",
    surface: str = "codex-cli",
    machine_id: str | None = None,
    model: str | None = "gpt-5",
):
    return create_launch(
        conn,
        auth=authorization(),
        request=LaunchRequest(
            project_id=10,
            executor_surface=surface,
            instructions=instructions,
            idempotency_key=key,
            machine_id=machine_id,
            model=model,
        ),
        now=NOW,
    ).launch


__all__ = [
    "NOW",
    "add_relay",
    "assigned_launch",
    "authorization",
    "launch_connection",
    "relay_connection",
]
