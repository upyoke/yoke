"""Additive, disposable pending-code storage for self-host machine sign-in."""

from typing import Any

from yoke_core.domain.schema_init_apply import execute_schema_script
from yoke_core.domain.schema_common import _add_column_if_not_exists


def create_machine_authorization_table(conn: Any) -> None:
    execute_schema_script(
        conn,
        """
        CREATE TABLE IF NOT EXISTS machine_authorization_codes (
            device_hash TEXT PRIMARY KEY,
            user_code TEXT NOT NULL UNIQUE,
            org_id INTEGER NOT NULL REFERENCES organizations(id),
            expires_at TEXT NOT NULL,
            actor_id INTEGER REFERENCES actors(id),
            machine_id TEXT,
            machine_name TEXT,
            consumed_at TEXT,
            client_key TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_machine_authorization_expiry
            ON machine_authorization_codes(expires_at);
        CREATE TABLE IF NOT EXISTS machine_authorization_rate_limits (
            client_key TEXT NOT NULL,
            operation TEXT NOT NULL,
            window_start INTEGER NOT NULL,
            request_count INTEGER NOT NULL,
            PRIMARY KEY (client_key, operation)
        );
        CREATE INDEX IF NOT EXISTS idx_machine_authorization_rate_window
            ON machine_authorization_rate_limits(window_start);
    """,
    )
    _add_column_if_not_exists(conn, "machine_authorization_codes", "client_key", "TEXT")
    conn.commit()
