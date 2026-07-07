"""Schema DDL for actor-token auth and project-role permissions."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.org_schema import REQUIRED_ORG_TABLES, create_org_tables
from yoke_core.domain.schema_init_apply import execute_schema_script


REQUIRED_AUTH_TABLES = (
    "api_tokens",
    "api_token_audit",
    "roles",
    "permissions",
    "role_permissions",
    "actor_project_roles",
    *REQUIRED_ORG_TABLES,
)


def create_auth_tables(conn: Any) -> None:
    """Create the cloud-runtime auth tables and indexes, idempotently."""
    execute_schema_script(conn, """
        CREATE TABLE IF NOT EXISTS api_tokens (
            id INTEGER PRIMARY KEY,
            token_hash TEXT NOT NULL UNIQUE,
            actor_id INTEGER NOT NULL REFERENCES actors(id),
            name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active'
                CHECK(status IN ('active','revoked')),
            created_at TEXT NOT NULL,
            revoked_at TEXT,
            expires_at TEXT,
            last_used_at TEXT,
            diagnostic_metadata TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_api_tokens_actor
            ON api_tokens(actor_id);
        CREATE INDEX IF NOT EXISTS idx_api_tokens_status
            ON api_tokens(status);

        CREATE TABLE IF NOT EXISTS api_token_audit (
            id INTEGER PRIMARY KEY,
            api_token_id INTEGER REFERENCES api_tokens(id),
            actor_id INTEGER REFERENCES actors(id),
            project_id INTEGER REFERENCES projects(id),
            event_type TEXT NOT NULL,
            outcome TEXT NOT NULL,
            permission_key TEXT,
            diagnostic_metadata TEXT,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_api_token_audit_token
            ON api_token_audit(api_token_id);
        CREATE INDEX IF NOT EXISTS idx_api_token_audit_actor
            ON api_token_audit(actor_id);
        CREATE INDEX IF NOT EXISTS idx_api_token_audit_project
            ON api_token_audit(project_id);

        CREATE TABLE IF NOT EXISTS roles (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            description TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS permissions (
            id INTEGER PRIMARY KEY,
            key TEXT NOT NULL UNIQUE,
            description TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS role_permissions (
            role_id INTEGER NOT NULL REFERENCES roles(id),
            permission_id INTEGER NOT NULL REFERENCES permissions(id),
            created_at TEXT NOT NULL,
            PRIMARY KEY (role_id, permission_id)
        );
        CREATE INDEX IF NOT EXISTS idx_role_permissions_permission
            ON role_permissions(permission_id);

        CREATE TABLE IF NOT EXISTS actor_project_roles (
            actor_id INTEGER NOT NULL REFERENCES actors(id),
            project_id INTEGER NOT NULL REFERENCES projects(id),
            role_id INTEGER NOT NULL REFERENCES roles(id),
            granted_at TEXT NOT NULL,
            granted_by_actor_id INTEGER REFERENCES actors(id),
            PRIMARY KEY (actor_id, project_id, role_id)
        );
        CREATE INDEX IF NOT EXISTS idx_actor_project_roles_project
            ON actor_project_roles(project_id);
        CREATE INDEX IF NOT EXISTS idx_actor_project_roles_role
            ON actor_project_roles(role_id);
    """)
    conn.commit()
    # Org scope lives in its own module but is part of the auth surface; create
    # it here so every auth-setup path (schema_init, tests) builds the same
    # shape. ``projects`` always precedes auth-table creation, so the
    # ``projects.org_id`` ALTER inside ``create_org_tables`` is safe.
    create_org_tables(conn)


def required_tables() -> tuple[str, ...]:
    return REQUIRED_AUTH_TABLES


__all__ = ["REQUIRED_AUTH_TABLES", "create_auth_tables", "required_tables"]
