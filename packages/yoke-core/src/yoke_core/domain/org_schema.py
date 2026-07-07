"""Schema DDL + seed for organizations and org-scoped role grants.

Orgs are the instance/auth scope above projects: every project belongs to
exactly one organization, and org role grants (``actor_org_roles``) carry the
global capabilities (``org.admin``, ``project.create``) that must not live on a
per-project role.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _column_exists
from yoke_core.domain.schema_init_apply import execute_schema_script


REQUIRED_ORG_TABLES = ("organizations", "actor_org_roles")

DEFAULT_ORG_SLUG = "default"
DEFAULT_ORG_NAME = "Default Org"


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def create_org_tables(conn: Any) -> None:
    """Create org tables + ``projects.org_id`` FK, idempotently."""
    execute_schema_script(conn, """
        CREATE TABLE IF NOT EXISTS organizations (
            id INTEGER PRIMARY KEY,
            slug TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS actor_org_roles (
            actor_id INTEGER NOT NULL REFERENCES actors(id),
            org_id INTEGER NOT NULL REFERENCES organizations(id),
            role_id INTEGER NOT NULL REFERENCES roles(id),
            granted_at TEXT NOT NULL,
            granted_by_actor_id INTEGER REFERENCES actors(id),
            PRIMARY KEY (actor_id, org_id, role_id)
        );
        CREATE INDEX IF NOT EXISTS idx_actor_org_roles_org
            ON actor_org_roles(org_id);
        CREATE INDEX IF NOT EXISTS idx_actor_org_roles_role
            ON actor_org_roles(role_id);
    """)
    # ``projects`` is created by the core schema; add the owning-org FK here so
    # both fresh-init and the migration converge on the same shape.
    if not _column_exists(conn, "projects", "org_id"):
        conn.execute(
            "ALTER TABLE projects ADD COLUMN org_id INTEGER REFERENCES organizations(id)"
        )
    conn.commit()


def ensure_project_slug_org_scope(conn: Any) -> None:
    """Ensure project slugs are unique inside their owning org."""
    if not _column_exists(conn, "projects", "org_id"):
        return
    rows = conn.execute(
        "SELECT org_id, slug, COUNT(*) AS count FROM projects "
        "GROUP BY org_id, slug HAVING COUNT(*) > 1 ORDER BY org_id, slug LIMIT 5"
    ).fetchall()
    if rows:
        samples = ", ".join(
            f"{row[0]}:{row[1]} ({row[2]})" for row in rows
        )
        raise AssertionError(f"duplicate project slugs within org: {samples}")
    if db_backend.connection_is_postgres(conn):
        conn.execute("ALTER TABLE projects ALTER COLUMN org_id SET NOT NULL")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_projects_org_slug_unique "
        "ON projects(org_id, slug)"
    )


def _sync_org_identity_sequence(conn: Any) -> None:
    if not db_backend.connection_is_postgres(conn):
        return
    row = conn.execute(
        "SELECT pg_get_serial_sequence('organizations', 'id') AS seq"
    ).fetchone()
    seq = row[0] if row else None
    if seq:
        conn.execute(
            "SELECT setval(%s, "
            "(SELECT COALESCE(MAX(id), 1) FROM organizations))",
            (seq,),
        )


def _set_project_org_default(conn: Any, org_id: int) -> None:
    if db_backend.connection_is_postgres(conn):
        conn.execute(
            "ALTER TABLE projects ALTER COLUMN org_id SET DEFAULT "
            f"{int(org_id)}"
        )


def org_id_by_slug(conn: Any, slug: str) -> int | None:
    p = _p(conn)
    row = conn.execute(
        f"SELECT id FROM organizations WHERE slug = {p}", (slug,)
    ).fetchone()
    return int(row[0]) if row else None


def rename_org(conn: Any, slug: str, name: str) -> None:
    """Set the display name on the org identity card addressed by slug."""
    p = _p(conn)
    conn.execute(
        f"UPDATE organizations SET name = {p} WHERE slug = {p}", (name, slug)
    )
    conn.commit()


def seed_default_org(conn: Any) -> int:
    """Ensure the default org exists and owns every unassigned project.

    Returns the default org id.
    """
    p = _p(conn)
    conn.execute(
        "INSERT INTO organizations (slug, name, created_at) "
        f"VALUES ({p}, {p}, {p}) "
        "ON CONFLICT(slug) DO NOTHING",
        (DEFAULT_ORG_SLUG, DEFAULT_ORG_NAME, _now()),
    )
    org_id = org_id_by_slug(conn, DEFAULT_ORG_SLUG)
    assert org_id is not None
    _sync_org_identity_sequence(conn)
    conn.execute(
        f"UPDATE projects SET org_id = {p} WHERE org_id IS NULL", (org_id,)
    )
    _set_project_org_default(conn, org_id)
    ensure_project_slug_org_scope(conn)
    conn.commit()
    return org_id


def ensure_org_identity_card(
    conn: Any, name: str | None = None,
) -> dict[str, str]:
    """Ensure the single-row org identity card, applying an optional name.

    Seeds the default org when absent; when ``name`` is given the card is
    renamed to it, otherwise the existing name stands (the seeded neutral
    default on a fresh universe). Returns ``{"slug": ..., "name": ...}``.
    """
    seed_default_org(conn)
    if name:
        rename_org(conn, DEFAULT_ORG_SLUG, name)
    row = conn.execute(
        "SELECT slug, name FROM organizations ORDER BY id LIMIT 1"
    ).fetchone()
    return {"slug": str(row[0]), "name": str(row[1])}


__all__ = [
    "REQUIRED_ORG_TABLES",
    "DEFAULT_ORG_SLUG",
    "DEFAULT_ORG_NAME",
    "create_org_tables",
    "ensure_org_identity_card",
    "ensure_project_slug_org_scope",
    "org_id_by_slug",
    "rename_org",
    "seed_default_org",
]
