"""Consolidate design documents into the canonical item structured field."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.schema_common import _column_exists, _table_exists


SOURCE_TABLE = "designs"
ITEMS_TABLE = "items"
TARGET_COLUMN = "design_spec"


def apply(conn: Any) -> None:
    """Move every legacy document without overwriting authored item content."""

    if not _table_exists(conn, ITEMS_TABLE):
        raise AssertionError(f"{ITEMS_TABLE} table is required before this migration")
    if not _column_exists(conn, ITEMS_TABLE, TARGET_COLUMN):
        raise AssertionError(
            f"{ITEMS_TABLE}.{TARGET_COLUMN} is required before this migration"
        )
    if not _table_exists(conn, SOURCE_TABLE):
        invariants(conn)
        return

    conn.execute(f"LOCK TABLE {ITEMS_TABLE}, {SOURCE_TABLE} IN ACCESS EXCLUSIVE MODE")
    orphaned = _count(
        conn,
        f"SELECT COUNT(*) FROM {SOURCE_TABLE} d "
        f"LEFT JOIN {ITEMS_TABLE} i ON i.id = d.item_id WHERE i.id IS NULL",
    )
    if orphaned:
        raise AssertionError(
            f"{SOURCE_TABLE} has {orphaned} documents without a matching item"
        )

    conflicts = _count(
        conn,
        f"SELECT COUNT(*) FROM {SOURCE_TABLE} d "
        f"JOIN {ITEMS_TABLE} i ON i.id = d.item_id "
        f"WHERE NULLIF(BTRIM(COALESCE(i.{TARGET_COLUMN}, '')), '') IS NOT NULL "
        f"AND i.{TARGET_COLUMN} IS DISTINCT FROM d.body",
    )
    if conflicts:
        raise AssertionError(
            f"{conflicts} items already have different {TARGET_COLUMN} content"
        )

    source_rows = _count(conn, f"SELECT COUNT(*) FROM {SOURCE_TABLE}")
    conn.execute(
        f"UPDATE {ITEMS_TABLE} AS i SET {TARGET_COLUMN} = d.body "
        f"FROM {SOURCE_TABLE} AS d WHERE i.id = d.item_id "
        f"AND NULLIF(BTRIM(COALESCE(i.{TARGET_COLUMN}, '')), '') IS NULL"
    )
    migrated_rows = _count(
        conn,
        f"SELECT COUNT(*) FROM {SOURCE_TABLE} d "
        f"JOIN {ITEMS_TABLE} i ON i.id = d.item_id "
        f"WHERE i.{TARGET_COLUMN} IS NOT DISTINCT FROM d.body",
    )
    if migrated_rows != source_rows:
        raise AssertionError(
            f"only {migrated_rows} of {source_rows} design documents were preserved"
        )

    conn.execute(f"DROP TABLE {SOURCE_TABLE}")
    invariants(conn)


def invariants(conn: Any) -> None:
    """Verify the obsolete storage surface is completely absent."""

    if not _table_exists(conn, ITEMS_TABLE):
        raise AssertionError(f"{ITEMS_TABLE} table is missing")
    if not _column_exists(conn, ITEMS_TABLE, TARGET_COLUMN):
        raise AssertionError(f"{ITEMS_TABLE}.{TARGET_COLUMN} is missing")
    if _table_exists(conn, SOURCE_TABLE):
        raise AssertionError(f"{SOURCE_TABLE} table is still present")


def _count(conn: Any, statement: str) -> int:
    row = conn.execute(statement).fetchone()
    return int(row[0]) if row is not None else 0


__all__ = [
    "ITEMS_TABLE",
    "SOURCE_TABLE",
    "TARGET_COLUMN",
    "apply",
    "invariants",
]
