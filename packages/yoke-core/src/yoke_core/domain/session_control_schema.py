"""Durable schema for fleet messages, launches, and machine relays."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.schema_init_apply import execute_schema_script
from yoke_core.domain.session_launch_surface_domain import (
    REQUESTED_SURFACE_COLUMN_DDL,
    SELECTED_SURFACE_COLUMN_DDL,
)


SESSION_CONTROL_TABLES = (
    "session_messages",
    "session_message_recipients",
    "session_message_attempts",
    "session_launches",
    "session_launch_attempts",
    "session_relays",
)


def create_session_control_tables(conn: Any) -> None:
    """Create additive fleet-control tables and lookup indexes."""
    execute_schema_script(
        conn,
        f"""
        CREATE TABLE IF NOT EXISTS session_messages (
            message_id TEXT PRIMARY KEY,
            sender_actor_id INTEGER NOT NULL REFERENCES actors(id),
            sender_session_id TEXT REFERENCES harness_sessions(session_id),
            body TEXT NOT NULL,
            body_sha256 TEXT NOT NULL,
            selector_snapshot TEXT NOT NULL,
            idempotency_key TEXT,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            cancelled_at TEXT,
            cancelled_by_actor_id INTEGER REFERENCES actors(id),
            cancellation_reason TEXT
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_session_messages_sender_dedupe
            ON session_messages(sender_actor_id, idempotency_key)
            WHERE idempotency_key IS NOT NULL;
        CREATE INDEX IF NOT EXISTS idx_session_messages_created
            ON session_messages(created_at);

        CREATE TABLE IF NOT EXISTS session_message_recipients (
            message_id TEXT NOT NULL REFERENCES session_messages(message_id),
            session_id TEXT NOT NULL REFERENCES harness_sessions(session_id),
            project_id INTEGER NOT NULL REFERENCES projects(id),
            resolution_evidence TEXT NOT NULL,
            routing_snapshot TEXT NOT NULL,
            executor_surface TEXT,
            executor_version TEXT,
            machine_id TEXT,
            state TEXT NOT NULL DEFAULT 'pending'
                CHECK(state IN ('pending','injected','acknowledged','expired','cancelled')),
            created_at TEXT NOT NULL,
            wake_after TEXT NOT NULL,
            injection_lease_id TEXT,
            injection_leased_at TEXT,
            injection_lease_expires_at TEXT,
            injection_count INTEGER NOT NULL DEFAULT 0,
            last_injected_at TEXT,
            acknowledged_at TEXT,
            expired_at TEXT,
            cancelled_at TEXT,
            wake_attempt_count INTEGER NOT NULL DEFAULT 0,
            last_wake_at TEXT,
            PRIMARY KEY (message_id, session_id)
        );
        CREATE INDEX IF NOT EXISTS idx_session_message_recipients_session_state
            ON session_message_recipients(session_id, state, created_at);
        CREATE INDEX IF NOT EXISTS idx_session_message_recipients_wake
            ON session_message_recipients(state, wake_after);
        CREATE INDEX IF NOT EXISTS idx_session_message_recipients_project
            ON session_message_recipients(project_id, state);

        CREATE TABLE IF NOT EXISTS session_message_attempts (
            attempt_id TEXT PRIMARY KEY,
            message_id TEXT NOT NULL,
            target_session_id TEXT NOT NULL,
            broker_session_id TEXT,
            attempt_kind TEXT NOT NULL
                CHECK(attempt_kind IN ('hook','wake_relay','wake_broker')),
            adapter_revision TEXT,
            lease_id TEXT,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            result_code TEXT,
            evidence TEXT,
            FOREIGN KEY (message_id, target_session_id)
                REFERENCES session_message_recipients(message_id, session_id),
            FOREIGN KEY (broker_session_id)
                REFERENCES harness_sessions(session_id)
        );
        CREATE INDEX IF NOT EXISTS idx_session_message_attempts_recipient
            ON session_message_attempts(message_id, target_session_id, started_at);

        CREATE TABLE IF NOT EXISTS session_launches (
            launch_id TEXT PRIMARY KEY,
            requester_actor_id INTEGER NOT NULL REFERENCES actors(id),
            requester_session_id TEXT REFERENCES harness_sessions(session_id),
            project_id INTEGER NOT NULL REFERENCES projects(id),
            requested_surface {REQUESTED_SURFACE_COLUMN_DDL},
            selected_surface {SELECTED_SURFACE_COLUMN_DDL},
            requested_machine_id TEXT,
            requested_model TEXT,
            presentation_preference TEXT,
            allow_surface_fallback INTEGER NOT NULL DEFAULT 0,
            message_id TEXT NOT NULL REFERENCES session_messages(message_id),
            idempotency_key TEXT,
            state TEXT NOT NULL DEFAULT 'queued'
                CHECK(state IN (
                    'queued','assigned','launching','awaiting_registration',
                    'succeeded','failed','cancelled','expired','outcome_unknown'
                )),
            assigned_relay_id TEXT,
            assigned_machine_id TEXT,
            native_session_id TEXT,
            attestation_hash TEXT,
            attestation_consumed_at TEXT,
            registered_session_id TEXT REFERENCES harness_sessions(session_id),
            deadline_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            assigned_at TEXT,
            launching_at TEXT,
            awaiting_registration_at TEXT,
            completed_at TEXT,
            result_code TEXT,
            result_evidence TEXT
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_session_launches_requester_dedupe
            ON session_launches(requester_actor_id, idempotency_key)
            WHERE idempotency_key IS NOT NULL;
        CREATE UNIQUE INDEX IF NOT EXISTS idx_session_launches_attestation
            ON session_launches(attestation_hash)
            WHERE attestation_hash IS NOT NULL;
        CREATE INDEX IF NOT EXISTS idx_session_launches_state_deadline
            ON session_launches(state, deadline_at);
        CREATE INDEX IF NOT EXISTS idx_session_launches_machine_state
            ON session_launches(assigned_machine_id, state);

        CREATE TABLE IF NOT EXISTS session_launch_attempts (
            attempt_id TEXT PRIMARY KEY,
            launch_id TEXT NOT NULL REFERENCES session_launches(launch_id),
            relay_id TEXT,
            machine_id TEXT NOT NULL,
            lease_id TEXT NOT NULL,
            batch_id TEXT,
            attempt_number INTEGER NOT NULL,
            adapter_revision TEXT,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            native_session_id TEXT,
            result_code TEXT,
            evidence TEXT,
            UNIQUE(launch_id, attempt_number)
        );
        CREATE INDEX IF NOT EXISTS idx_session_launch_attempts_launch
            ON session_launch_attempts(launch_id, started_at);

        CREATE TABLE IF NOT EXISTS session_relays (
            relay_id TEXT PRIMARY KEY,
            actor_id INTEGER NOT NULL REFERENCES actors(id),
            machine_id TEXT NOT NULL,
            hostname TEXT NOT NULL,
            relay_version TEXT,
            surface_versions TEXT NOT NULL,
            project_checkouts TEXT NOT NULL,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            connected_until TEXT NOT NULL,
            last_job_at TEXT,
            state TEXT NOT NULL DEFAULT 'active'
                CHECK(state IN ('active','idle','revoked')),
            lease_id TEXT,
            lease_expires_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_session_relays_machine_connected
            ON session_relays(machine_id, connected_until);
        CREATE INDEX IF NOT EXISTS idx_session_relays_state_connected
            ON session_relays(state, connected_until);
    """,
    )


def required_tables() -> tuple[str, ...]:
    return SESSION_CONTROL_TABLES


__all__ = [
    "SESSION_CONTROL_TABLES",
    "create_session_control_tables",
    "required_tables",
]
