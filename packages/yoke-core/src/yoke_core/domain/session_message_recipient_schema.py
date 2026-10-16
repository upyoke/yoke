"""Recipient storage created before message attempts reference its composite key."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.schema_common import _add_column_if_not_exists
from yoke_core.domain.schema_init_apply import execute_schema_script


def create_session_message_recipient_table(conn: Any) -> None:
    """Create recipient storage and converge additive org lookup support."""
    execute_schema_script(
        conn,
        """
        CREATE TABLE IF NOT EXISTS session_message_recipients (
            message_id TEXT NOT NULL REFERENCES session_messages(message_id),
            session_id TEXT NOT NULL REFERENCES harness_sessions(session_id),
            project_id INTEGER REFERENCES projects(id),
            org_id INTEGER REFERENCES organizations(id),
            resolution_evidence TEXT NOT NULL,
            routing_snapshot TEXT NOT NULL,
            executor_surface TEXT,
            executor_version TEXT,
            machine_id TEXT,
            state TEXT NOT NULL DEFAULT 'pending'
                CHECK(state IN ('pending','injected','acknowledged','expired','cancelled')),
            created_at TIMESTAMPTZ NOT NULL,
            wake_after TIMESTAMPTZ NOT NULL,
            injection_lease_id TEXT,
            injection_leased_at TIMESTAMPTZ,
            injection_lease_expires_at TIMESTAMPTZ,
            injection_count INTEGER NOT NULL DEFAULT 0,
            last_injected_at TIMESTAMPTZ,
            acknowledged_at TIMESTAMPTZ,
            expired_at TIMESTAMPTZ,
            cancelled_at TIMESTAMPTZ,
            wake_attempt_count INTEGER NOT NULL DEFAULT 0,
            last_wake_at TIMESTAMPTZ,
            wake_escalation TEXT,
            PRIMARY KEY (message_id, session_id),
            CONSTRAINT session_message_recipients_scope_exactly_one CHECK (
                (project_id IS NOT NULL AND org_id IS NULL)
                OR (project_id IS NULL AND org_id IS NOT NULL)
            )
        );
        CREATE INDEX IF NOT EXISTS idx_session_message_recipients_session_state
            ON session_message_recipients(session_id, state, created_at);
        CREATE INDEX IF NOT EXISTS idx_session_message_recipients_wake
            ON session_message_recipients(state, wake_after);
        CREATE INDEX IF NOT EXISTS idx_session_message_recipients_project
            ON session_message_recipients(project_id, state);
        """,
    )
    _add_column_if_not_exists(
        conn,
        "session_message_recipients",
        "org_id",
        "INTEGER REFERENCES organizations(id)",
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_session_message_recipients_org "
        "ON session_message_recipients(org_id)"
    )
