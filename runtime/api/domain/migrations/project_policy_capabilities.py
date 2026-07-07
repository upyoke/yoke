"""Install shared project policy capability rows."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.project_policy_capabilities import (
    PROJECT_POLICY_CAPABILITY,
    SESSION_ROUTING_CAPABILITY,
    ensure_default_policy_capabilities,
)
from yoke_core.domain.schema_common import _table_exists


def apply(conn: Any) -> None:
    """Create or repair DB-backed project policy capability settings."""

    if not _table_exists(conn, "projects"):
        raise AssertionError("projects table is required before this migration")
    if not _table_exists(conn, "project_capabilities"):
        raise AssertionError(
            "project_capabilities table is required before this migration"
        )
    ensure_default_policy_capabilities(conn)


def invariants(conn: Any) -> None:
    """Verify every project has both policy capability rows."""

    if not _table_exists(conn, "projects"):
        raise AssertionError("projects table is missing")
    if not _table_exists(conn, "project_capabilities"):
        raise AssertionError("project_capabilities table is missing")
    missing = conn.execute(
        """
        SELECT p.id
        FROM projects p
        WHERE NOT EXISTS (
            SELECT 1 FROM project_capabilities pc
            WHERE pc.project_id = p.id AND pc.type = %s
        )
        OR NOT EXISTS (
            SELECT 1 FROM project_capabilities pc
            WHERE pc.project_id = p.id AND pc.type = %s
        )
        ORDER BY p.id
        LIMIT 5
        """,
        (PROJECT_POLICY_CAPABILITY, SESSION_ROUTING_CAPABILITY),
    ).fetchall()
    if missing:
        samples = ", ".join(str(row[0]) for row in missing)
        raise AssertionError(
            f"projects missing policy capability rows: {samples}"
        )
