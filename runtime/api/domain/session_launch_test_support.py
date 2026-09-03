"""SQLite fixtures for focused session-launch state-machine tests."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from yoke_contracts.session_control.plan_limits import ALL_MODELS_SCOPE
from yoke_core.domain.machine_registry_schema import ensure_machine_registry_schema
from yoke_core.domain.session_control_schema import create_session_control_tables
from yoke_core.domain.session_launch_requests import create_launch
from yoke_core.domain.session_launch_types import LaunchAuthorization, LaunchRequest
from yoke_core.domain.work_claim_targets import make_steering_target


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
            model TEXT,
            reasoning_effort TEXT DEFAULT NULL,
            context_window_tokens INTEGER DEFAULT NULL,
            requested_model TEXT DEFAULT NULL,
            requested_reasoning_effort TEXT DEFAULT NULL,
            requested_context_window_tokens INTEGER DEFAULT NULL,
            keepalive_until TEXT,
            keepalive_reason TEXT,
            ended_at TEXT
        );
        INSERT INTO actors (id) VALUES (1), (2), (3);
        INSERT INTO projects (id, slug) VALUES (10, 'launch-project');
        INSERT INTO harness_sessions (
            session_id, project_id, executor_surface, executor_version,
            machine_id, model
        ) VALUES ('caller', 10, 'codex-desktop', '26.814.41407', 'm0', 'gpt-5');
        CREATE TABLE work_claims (
            id INTEGER PRIMARY KEY,
            session_id TEXT NOT NULL,
            target_kind TEXT NOT NULL DEFAULT 'item',
            scope TEXT NOT NULL DEFAULT '{}',
            claim_type TEXT NOT NULL DEFAULT 'exclusive',
            claimed_at TEXT NOT NULL DEFAULT '',
            last_heartbeat TEXT NOT NULL DEFAULT '',
            released_at TEXT
        );
        """
    )
    ensure_machine_registry_schema(conn, commit=False)
    create_session_control_tables(conn)
    conn.commit()
    return conn


def add_steering_claim(
    conn: sqlite3.Connection,
    *,
    session_id: str = "caller",
    project_id: int = 10,
    released_at: str | None = None,
) -> None:
    target = make_steering_target(project_id)
    conn.execute(
        "INSERT INTO work_claims "
        "(session_id, target_kind, scope, claim_type, claimed_at, "
        "last_heartbeat, released_at) VALUES (?, ?, ?, 'exclusive', ?, ?, ?)",
        (session_id, target.kind, target.scope_json(), NOW, NOW, released_at),
    )
    conn.commit()


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
    conn.execute("ALTER TABLE harness_sessions ADD COLUMN terminated_at TEXT")
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


def register_machine_row(
    conn: sqlite3.Connection,
    *,
    machine_id: str,
    actor_id: int = 1,
    name: str | None = None,
    access: dict[str, Any] | None = None,
) -> None:
    """Seed one registered machine directly, the way relays are seeded here."""
    conn.execute(
        "INSERT OR REPLACE INTO machines "
        "(machine_id, name, owner_actor_id, proof_public_key, access, "
        "registered_at, last_seen_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            machine_id,
            name or machine_id,
            actor_id,
            "seeded-public-key",
            json.dumps(access or {}),
            NOW,
            NOW,
        ),
    )
    conn.commit()


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
    plan_limits: dict[str, Any] | None = None,
    preferred_models: dict[str, str] | None = None,
    registered: bool = True,
) -> None:
    if registered:
        register_machine_row(conn, machine_id=machine_id, actor_id=actor_id)
    conn.execute(
        "INSERT INTO session_relays "
        "(relay_id, actor_id, machine_id, hostname, surface_versions, "
        "project_checkouts, first_seen_at, last_seen_at, connected_until, state, "
        "surface_plan_limits, preferred_session_models) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)",
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
            json.dumps(plan_limits or {}),
            json.dumps(preferred_models or {}),
        ),
    )
    conn.commit()


def plan_limit_document(
    surface: str,
    *,
    remaining_percent: float,
    resets_at: str,
    window_kind: str = "rolling_5h",
) -> dict[str, Any]:
    """One machine's published meter for a surface, as the relay stores it."""
    return {
        surface: {
            "plan_tier": "max",
            "windows": [
                {
                    "window_kind": window_kind,
                    "scope": ALL_MODELS_SCOPE,
                    "remaining_percent": remaining_percent,
                    "resets_at": resets_at,
                    "status": "ok",
                }
            ],
        }
    }


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
    "add_steering_claim",
    "assigned_launch",
    "authorization",
    "launch_connection",
    "plan_limit_document",
    "register_machine_row",
    "relay_connection",
]
