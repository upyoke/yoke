"""Allow sessions and their durable delivery work to name a project or an org.

Existing project-scoped rows retain their scope and identifiers; no rows are
rewritten. Older builds cast project ids to integers, so they cannot serve a
converged database once org-scoped sessions exist. The next-release serving
floor prevents those builds from serving this shape. Registration remains
project-required until all nullable readers have landed.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.migration_serving_version import NEXT_RELEASE
from yoke_core.domain.schema_common import (
    _column_exists,
    _column_is_not_null,
    _index_exists,
    _table_exists,
)

MINIMUM_SERVING_VERSION = NEXT_RELEASE
TABLES = (
    "harness_sessions",
    "session_message_recipients",
    "session_termination_reaps",
    "session_evidence_fetches",
)
SCOPE_PREDICATE = (
    "(project_id IS NOT NULL AND org_id IS NULL) "
    "OR (project_id IS NULL AND org_id IS NOT NULL)"
)


def _constraint_exists(conn: Any, table: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM pg_constraint WHERE conrelid = to_regclass(%s) "
            "AND conname = %s AND contype = 'c' AND convalidated",
            (table, f"{table}_scope_exactly_one"),
        ).fetchone()
        is not None
    )


def apply(conn: Any) -> None:
    """Relax project scope and constrain the two scope columns atomically."""
    for table in TABLES:
        if not _table_exists(conn, table):
            continue
        if not _column_exists(conn, table, "org_id"):
            conn.execute(
                f"ALTER TABLE {table} ADD COLUMN org_id "
                "INTEGER REFERENCES organizations(id)"
            )
        conn.execute(f"ALTER TABLE {table} ALTER COLUMN project_id DROP NOT NULL")
        if not _constraint_exists(conn, table):
            conn.execute(
                f"ALTER TABLE {table} ADD CONSTRAINT {table}_scope_exactly_one "
                f"CHECK ({SCOPE_PREDICATE})"
            )
        conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_org ON {table}(org_id)")


def invariants(conn: Any) -> None:
    """Prove the scope shape and every existing row satisfy the contract."""
    for table in TABLES:
        if not _table_exists(conn, table):
            continue
        checks = (
            (_column_exists(conn, table, "org_id"), "org_id is missing"),
            (_column_exists(conn, table, "project_id"), "project_id is missing"),
            (
                not _column_is_not_null(conn, table, "project_id"),
                "project_id is required",
            ),
            (not _column_is_not_null(conn, table, "org_id"), "org_id is required"),
            (_constraint_exists(conn, table), "validated scope constraint is missing"),
            (_index_exists(conn, f"idx_{table}_org", table), "org index is missing"),
        )
        for passed, reason in checks:
            if not passed:
                raise RuntimeError(
                    f"session_scope_unconverged: {table}: {reason}. Recovery: "
                    "boot the candidate to converge its governed migration history."
                )
        invalid = conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE NOT ({SCOPE_PREDICATE})"
        ).fetchone()[0]
        if invalid:
            raise RuntimeError(
                f"session_scope_invalid: {table} has {invalid} rows with ambiguous "
                "or missing scope. Recovery: repair through the registered row "
                "owner, then reboot the candidate to rerun convergence."
            )
