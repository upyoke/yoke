"""Durable schema for fleet messages, launches, and machine relays."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.actor_message_recipient_schema import (
    RECIPIENT_KIND_STATE_CONSTRAINT,
    RECIPIENT_KIND_STATE_PREDICATE,
    converge_role_addressed_recipients,
)
from yoke_core.domain.machine_registry_schema import ensure_machine_registry_schema
from yoke_core.domain.schema_common import _column_exists
from yoke_core.domain.schema_init_apply import execute_schema_script
from yoke_contracts.session_control.launch_origin import ORIGIN_COLUMN_DDL
from yoke_contracts.session_control.sender_surface import SENDER_SURFACES
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
    "session_termination_reaps",
    "session_evidence_fetches",
    "session_surface_policies",
)
ACTOR_MESSAGE_TABLES = ("actor_message_recipients",)
_SENDER_SURFACE_VALUES = ",".join(f"'{value}'" for value in SENDER_SURFACES)


def create_session_control_tables(conn: Any) -> None:
    """Create additive fleet-control tables and lookup indexes.

    Every table here names a machine, so the registry owning those ids
    converges first — once here, not once per call site.
    """
    ensure_machine_registry_schema(conn, commit=False)
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
            cancellation_reason TEXT,
            sender_surface TEXT CHECK(sender_surface IN ({_SENDER_SURFACE_VALUES}))
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
            wake_escalation TEXT,
            PRIMARY KEY (message_id, session_id)
        );
        CREATE INDEX IF NOT EXISTS idx_session_message_recipients_session_state
            ON session_message_recipients(session_id, state, created_at);
        CREATE INDEX IF NOT EXISTS idx_session_message_recipients_wake
            ON session_message_recipients(state, wake_after);
        CREATE INDEX IF NOT EXISTS idx_session_message_recipients_project
            ON session_message_recipients(project_id, state);

        CREATE TABLE IF NOT EXISTS actor_message_recipients (
            message_id TEXT NOT NULL REFERENCES session_messages(message_id),
            recipient_kind TEXT NOT NULL DEFAULT 'actor',
            actor_id INTEGER REFERENCES actors(id),
            state TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            read_at TEXT,
            expired_at TEXT,
            steering_scope TEXT,
            sender_item_id INTEGER REFERENCES items(id),
            project_id INTEGER REFERENCES projects(id),
            seat_session_id TEXT REFERENCES harness_sessions(session_id),
            seat_claim_id INTEGER REFERENCES work_claims(id),
            delivered_at TEXT,
            acknowledged_at TEXT,
            UNIQUE(message_id, actor_id),
            CONSTRAINT {RECIPIENT_KIND_STATE_CONSTRAINT} CHECK (
                {RECIPIENT_KIND_STATE_PREDICATE}
            )
        );
        CREATE INDEX IF NOT EXISTS idx_actor_message_recipients_actor_state
            ON actor_message_recipients(actor_id, state, created_at);

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
            session_name TEXT,
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
            result_evidence TEXT,
            origin {ORIGIN_COLUMN_DDL},
            native_launch_pid INTEGER,
            native_launch_phase TEXT,
            native_launch_observed_at TEXT,
            spawn_duration_ms INTEGER,
            spawn_hold_reason TEXT,
            placement_reason TEXT,
            resolved_model TEXT
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
            lease_expires_at TEXT,
            surface_plan_limits TEXT,
            machine_capacity TEXT,
            preferred_session_models TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_session_relays_machine_connected
            ON session_relays(machine_id, connected_until);
        CREATE INDEX IF NOT EXISTS idx_session_relays_state_connected
            ON session_relays(state, connected_until);

        CREATE TABLE IF NOT EXISTS session_termination_reaps (
            target_session_id TEXT PRIMARY KEY REFERENCES harness_sessions(session_id),
            project_id INTEGER NOT NULL REFERENCES projects(id),
            machine_id TEXT,
            executor_surface TEXT,
            target_native_thread_id TEXT,
            launch_id TEXT REFERENCES session_launches(launch_id),
            state TEXT NOT NULL
                CHECK(state IN ('pending','leased','succeeded','failed','unavailable')),
            requested_at TEXT NOT NULL,
            lease_id TEXT,
            lease_expires_at TEXT,
            completed_at TEXT,
            result_code TEXT,
            evidence TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_session_termination_reaps_machine_state
            ON session_termination_reaps(machine_id, state, requested_at);

        CREATE TABLE IF NOT EXISTS session_evidence_fetches (
            fetch_id TEXT PRIMARY KEY,
            target_session_id TEXT NOT NULL
                REFERENCES harness_sessions(session_id),
            project_id INTEGER NOT NULL REFERENCES projects(id),
            machine_id TEXT NOT NULL,
            kind TEXT,
            file_name TEXT,
            diagnostic_ref TEXT,
            tail_lines INTEGER NOT NULL,
            state TEXT NOT NULL
                CHECK(state IN ('pending','leased','succeeded','failed','expired')),
            requested_at TEXT NOT NULL,
            requested_by_actor_id INTEGER NOT NULL REFERENCES actors(id),
            requested_by_session_id TEXT REFERENCES harness_sessions(session_id),
            lease_id TEXT,
            lease_expires_at TEXT,
            completed_at TEXT,
            result_code TEXT,
            files TEXT,
            selected_file TEXT,
            content TEXT,
            content_bytes INTEGER,
            truncated INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_session_evidence_fetches_machine_state
            ON session_evidence_fetches(machine_id, state, requested_at);
        CREATE INDEX IF NOT EXISTS idx_session_evidence_fetches_target_state
            ON session_evidence_fetches(target_session_id, state, requested_at);

        CREATE TABLE IF NOT EXISTS session_surface_policies (
            mark_id TEXT PRIMARY KEY,
            machine_id TEXT NOT NULL,
            surface TEXT NOT NULL,
            state TEXT NOT NULL CHECK(state IN ('disabled')),
            reason TEXT NOT NULL,
            evidence TEXT,
            set_by_actor_id INTEGER NOT NULL REFERENCES actors(id),
            set_by_session_id TEXT REFERENCES harness_sessions(session_id),
            created_at TEXT NOT NULL,
            cleared_at TEXT,
            cleared_by_actor_id INTEGER REFERENCES actors(id)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_session_surface_policies_live
            ON session_surface_policies(machine_id, surface)
            WHERE cleared_at IS NULL;
        CREATE INDEX IF NOT EXISTS idx_session_surface_policies_machine
            ON session_surface_policies(machine_id, created_at);
    """,
    )
    # CREATE TABLE IF NOT EXISTS never alters an existing table, so a column
    # introduced after a table first shipped must also converge as an additive
    # ALTER for databases born before it.
    for table, name, column_type in (
        ("session_launch_attempts", "batch_id", "TEXT"),
        ("session_launches", "origin", ORIGIN_COLUMN_DDL),
        ("session_launches", "session_name", "TEXT"),
        ("session_launches", "native_launch_pid", "INTEGER"),
        ("session_launches", "native_launch_phase", "TEXT"),
        ("session_launches", "native_launch_observed_at", "TEXT"),
        ("session_launches", "spawn_duration_ms", "INTEGER"),
        ("session_launches", "spawn_hold_reason", "TEXT"),
        ("session_launches", "placement_reason", "TEXT"),
        ("session_launches", "resolved_model", "TEXT"),
        ("session_relays", "surface_plan_limits", "TEXT"),
        ("session_relays", "machine_capacity", "TEXT"),
        ("session_relays", "preferred_session_models", "TEXT"),
        ("session_message_recipients", "wake_escalation", "TEXT"),
    ):
        if not _column_exists(conn, table, name):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {column_type}")
    if not _column_exists(conn, "session_messages", "sender_surface"):
        conn.execute(
            "ALTER TABLE session_messages ADD COLUMN sender_surface TEXT "
            f"CHECK(sender_surface IN ({_SENDER_SURFACE_VALUES}))"
        )
    converge_role_addressed_recipients(conn)


def required_tables() -> tuple[str, ...]:
    return SESSION_CONTROL_TABLES + ACTOR_MESSAGE_TABLES


__all__ = [
    "ACTOR_MESSAGE_TABLES",
    "SESSION_CONTROL_TABLES",
    "create_session_control_tables",
    "required_tables",
]
