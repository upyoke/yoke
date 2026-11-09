"""Organization identity table required by project and session schemas."""

from typing import Any

from yoke_core.domain.schema_init_apply import execute_schema_script


def create_organization_table(conn: Any) -> None:
    """Create org identity before session scope or role grants reference it."""
    execute_schema_script(
        conn,
        """
        CREATE TABLE IF NOT EXISTS organizations (
            id INTEGER PRIMARY KEY,
            slug TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            domain TEXT DEFAULT NULL,
            settings TEXT NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL
        );
        """,
    )

