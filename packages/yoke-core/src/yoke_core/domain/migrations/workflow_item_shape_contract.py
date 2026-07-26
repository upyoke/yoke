"""Contract item storage onto immutable workflow pins."""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _column_exists, _table_exists
from yoke_core.domain.workflow_runtime import (
    ENGINE_EXCEPTIONAL_STAGE_IDS,
    load_item_workflow_runtime,
)
from yoke_core.domain.workflow_registry import WorkflowRegistryError

MIGRATION_NAME = "workflow_item_shape_contract"
_RETIRED_CLASSIFICATION_COLUMN = "type"
_PIN_COLUMNS = ("workflow_id", "workflow_version_id")


def _quote_identifier(raw: str) -> str:
    return '"' + raw.replace('"', '""') + '"'


def _status_check_constraints(conn: Any) -> tuple[str, ...]:
    rows = conn.execute(
        "SELECT DISTINCT con.conname "
        "FROM pg_catalog.pg_constraint con "
        "JOIN pg_catalog.pg_attribute attr "
        "ON attr.attrelid = con.conrelid "
        "AND attr.attnum = ANY(con.conkey) "
        "WHERE con.conrelid = 'items'::regclass "
        "AND con.contype = 'c' "
        "AND attr.attname = 'status' "
        "ORDER BY con.conname"
    ).fetchall()
    return tuple(str(row[0]) for row in rows)


def _assert_valid_pins_and_stages(conn: Any) -> None:
    invalid_pins = conn.execute(
        "SELECT i.id FROM items i "
        "LEFT JOIN workflow_versions v ON v.id = i.workflow_version_id "
        "WHERE i.workflow_id IS NULL OR i.workflow_version_id IS NULL "
        "OR v.id IS NULL OR v.workflow_id <> i.workflow_id "
        "ORDER BY i.id LIMIT 5"
    ).fetchall()
    if invalid_pins:
        samples = ", ".join(str(row[0]) for row in invalid_pins)
        raise AssertionError(f"items have invalid workflow pins: {samples}")

    invalid_stages: list[str] = []
    rows = conn.execute("SELECT id, status FROM items ORDER BY id").fetchall()
    for item_id, status in rows:
        try:
            runtime = load_item_workflow_runtime(conn, int(item_id))
        except WorkflowRegistryError as exc:
            invalid_stages.append(f"{item_id}:{exc}")
            continue
        stage_id = str(status)
        if (
            stage_id not in runtime.stage_ids
            and stage_id not in ENGINE_EXCEPTIONAL_STAGE_IDS
        ):
            invalid_stages.append(
                f"{item_id}:{stage_id} not in {runtime.workflow_id}@{runtime.version}"
            )
    if invalid_stages:
        raise AssertionError(
            "items have invalid workflow stages: " + ", ".join(invalid_stages[:5])
        )


def _assert_column_required(conn: Any, column: str) -> None:
    row = conn.execute(
        "SELECT is_nullable FROM information_schema.columns "
        "WHERE table_schema = current_schema() "
        "AND table_name = 'items' AND column_name = %s",
        (column,),
    ).fetchone()
    if row is None or str(row[0]) != "NO":
        raise AssertionError(f"items.{column} must be NOT NULL")


def apply(conn: Any) -> None:
    """Remove superseded item shape after validating immutable pins."""
    if not db_backend.connection_is_postgres(conn):
        raise RuntimeError("workflow item shape contraction requires PostgreSQL")
    if not _table_exists(conn, "items"):
        raise AssertionError("items table is required before this migration")
    for column in _PIN_COLUMNS:
        if not _column_exists(conn, "items", column):
            raise AssertionError(f"items.{column} is required before contraction")

    conn.execute("LOCK TABLE items IN ACCESS EXCLUSIVE MODE")
    before = int(conn.execute("SELECT COUNT(*) FROM items").fetchone()[0])
    _assert_valid_pins_and_stages(conn)

    for constraint in _status_check_constraints(conn):
        conn.execute(
            f"ALTER TABLE items DROP CONSTRAINT {_quote_identifier(constraint)}"
        )
    conn.execute("ALTER TABLE items ALTER COLUMN status DROP DEFAULT")
    for column in _PIN_COLUMNS:
        conn.execute(
            f"ALTER TABLE items ALTER COLUMN {_quote_identifier(column)} SET NOT NULL"
        )
    if _column_exists(conn, "items", _RETIRED_CLASSIFICATION_COLUMN):
        conn.execute(
            "ALTER TABLE items DROP COLUMN "
            f"{_quote_identifier(_RETIRED_CLASSIFICATION_COLUMN)}"
        )

    after = int(conn.execute("SELECT COUNT(*) FROM items").fetchone()[0])
    if after != before:
        raise AssertionError(f"items row count changed from {before} to {after}")


def invariants(conn: Any) -> None:
    """Verify the workflow pin is the only item behavior authority."""
    if not _table_exists(conn, "items"):
        raise AssertionError("items table is missing")
    if _column_exists(conn, "items", _RETIRED_CLASSIFICATION_COLUMN):
        raise AssertionError("retired item classification column is still present")
    if _status_check_constraints(conn):
        raise AssertionError("items.status still has a fixed vocabulary constraint")
    for column in _PIN_COLUMNS:
        _assert_column_required(conn, column)
    _assert_valid_pins_and_stages(conn)


__all__ = ["MIGRATION_NAME", "apply", "invariants"]
