"""Additive, disposable pending-code storage for self-host machine sign-in."""

from typing import Any

from yoke_core.domain.schema_init_apply import execute_schema_script


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
            consumed_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_machine_authorization_expiry
            ON machine_authorization_codes(expires_at);
    """,
    )
    conn.commit()
