"""Converge the immutable workflow registry and nullable item pins."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.builtin_workflow_definitions import BUILTIN_WORKFLOW_IDS
from yoke_core.domain.schema_common import _column_exists, _table_exists
from yoke_core.domain.workflow_registry import converge_builtin_workflows
from yoke_core.domain.workflow_schema import ensure_workflow_schema

MIGRATION_NAME = "workflow_registry_foundation"


def apply(conn: Any) -> None:
    """Create the additive registry shape and seed its first versions."""
    ensure_workflow_schema(conn)
    converge_builtin_workflows(conn)


def invariants(conn: Any) -> None:
    """Verify registry coherence without requiring legacy-item backfill."""
    for table in ("workflows", "workflow_versions"):
        if not _table_exists(conn, table):
            raise AssertionError(f"{table} table is missing")
    for column in ("workflow_id", "workflow_version_id", "workflow_posture"):
        if not _column_exists(conn, "items", column):
            raise AssertionError(f"items.{column} is missing")

    rows = conn.execute(
        "SELECT w.id, w.current_version_id, v.workflow_id "
        "FROM workflows w "
        "LEFT JOIN workflow_versions v ON v.id = w.current_version_id "
        "ORDER BY w.id"
    ).fetchall()
    by_id = {str(row[0]): row for row in rows}
    missing = set(BUILTIN_WORKFLOW_IDS) - set(by_id)
    if missing:
        raise AssertionError(f"built-in workflows are missing: {sorted(missing)}")
    for workflow_id, row in by_id.items():
        if row[1] is None or str(row[2]) != workflow_id:
            raise AssertionError(
                f"workflow {workflow_id!r} has an invalid current version"
            )

    invalid_pins = conn.execute(
        "SELECT i.id FROM items i "
        "LEFT JOIN workflow_versions v ON v.id = i.workflow_version_id "
        "WHERE (i.workflow_id IS NULL) <> (i.workflow_version_id IS NULL) "
        "OR (i.workflow_id IS NOT NULL AND "
        "(v.id IS NULL OR v.workflow_id <> i.workflow_id)) "
        "ORDER BY i.id LIMIT 5"
    ).fetchall()
    if invalid_pins:
        samples = ", ".join(str(row[0]) for row in invalid_pins)
        raise AssertionError(f"items have invalid workflow pins: {samples}")


__all__ = ["MIGRATION_NAME", "apply", "invariants"]
