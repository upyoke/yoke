"""Pending timers stay separate from messages until their due instant."""

from typing import Any

from yoke_core.domain.schema_init_apply import execute_schema_script


def create_session_scheduled_wakes(conn: Any) -> None:
    execute_schema_script(
        conn,
        """
        CREATE TABLE IF NOT EXISTS session_scheduled_wakes (
            wake_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES harness_sessions(session_id) ON DELETE CASCADE,
            actor_id INTEGER NOT NULL REFERENCES actors(id),
            due_at TIMESTAMPTZ NOT NULL,
            reason TEXT NOT NULL CHECK(TRIM(reason) <> ''),
            created_at TIMESTAMPTZ NOT NULL,
            message_id TEXT REFERENCES session_messages(message_id) ON DELETE CASCADE,
            UNIQUE(session_id,due_at,reason)
        );
        CREATE INDEX IF NOT EXISTS idx_session_scheduled_wakes_due
            ON session_scheduled_wakes(due_at) WHERE message_id IS NULL;
    """,
    )
