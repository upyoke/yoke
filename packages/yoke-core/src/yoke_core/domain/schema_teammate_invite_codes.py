"""Additive storage for single-use teammate admission secrets."""

from typing import Any

from yoke_core.domain.schema_init_apply import execute_schema_script


def create_teammate_invite_codes_table(conn: Any) -> None:
    execute_schema_script(
        conn,
        """
        CREATE TABLE IF NOT EXISTS teammate_invite_codes (
            id INTEGER PRIMARY KEY,
            actor_id INTEGER NOT NULL REFERENCES actors(id),
            org_id INTEGER NOT NULL REFERENCES organizations(id),
            role TEXT NOT NULL,
            code_hash TEXT NOT NULL UNIQUE,
            request_id TEXT UNIQUE,
            invited_by_actor_id INTEGER NOT NULL REFERENCES actors(id),
            created_at TIMESTAMPTZ NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            consumed_at TIMESTAMPTZ,
            consumed_machine_id TEXT,
            revoked_at TIMESTAMPTZ,
            replaced_at TIMESTAMPTZ
        );
        CREATE INDEX IF NOT EXISTS idx_teammate_invite_codes_actor
            ON teammate_invite_codes(actor_id);
        """,
    )
