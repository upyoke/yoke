"""Replace Shepherd's internal-id tokens with project-scoped public refs.

The old ``item`` column encoded ``YOK-{items.id}``, irrespective of project.
Renaming the column makes the cutover distinguishable from its output even
when an old token happens to be a different item's valid public ref.
"""

from __future__ import annotations

import re
from typing import Any

from yoke_core.domain.db_backend import connection_is_postgres
from yoke_core.domain.migration_serving_version import NEXT_RELEASE
from yoke_core.domain.schema_common import _column_exists, _table_exists

MINIMUM_SERVING_VERSION = NEXT_RELEASE
_TABLES = ("shepherd_verdicts", "caveat_dispositions")
_OLD_KEY = re.compile(r"^YOK-([1-9][0-9]*)$")


def _marker(conn: Any) -> str:
    return "%s" if connection_is_postgres(conn) else "?"


def _identity(conn: Any, key: str) -> str:
    match = _OLD_KEY.fullmatch(key)
    row = None
    if match:
        row = conn.execute(
            "SELECT p.public_item_prefix, i.project_sequence FROM items i "
            "JOIN projects p ON p.id = i.project_id "
            f"WHERE i.id = {_marker(conn)}",
            (int(match.group(1)),),
        ).fetchone()
    if row is None or not row[0] or row[1] is None:
        raise RuntimeError(
            "shepherd_key_unresolved: a stored Shepherd key has no item identity. "
            "Recovery: inspect the Shepherd records on the current serving "
            "build and repair their item association, then rehearse this migration."
        )
    return f"{row[0]}-{row[1]}"


def apply(conn: Any) -> None:
    for table in _TABLES:
        if not _table_exists(conn, table) or not _column_exists(conn, table, "item"):
            continue
        # Resolve the entire table before changing anything. The runner owns
        # the transaction; verdict ids and every caveat's verdict FK survive.
        rows = conn.execute(f"SELECT id, item FROM {table} ORDER BY id").fetchall()
        updates = [(_identity(conn, str(row[1])), row[0]) for row in rows]
        # Keys can permute (an internal id can equal another public sequence).
        # Vacate the old namespace first without dropping uniqueness or rows.
        for _, row_id in updates:
            conn.execute(
                f"UPDATE {table} SET item = {_marker(conn)} WHERE id = {_marker(conn)}",
                (f"@{row_id}", row_id),
            )
        for public_ref, row_id in updates:
            conn.execute(
                f"UPDATE {table} SET item = {_marker(conn)} WHERE id = {_marker(conn)}",
                (public_ref, row_id),
            )
        conn.execute(f"ALTER TABLE {table} RENAME COLUMN item TO public_ref")


def invariants(conn: Any) -> None:
    for table in _TABLES:
        if not _table_exists(conn, table):
            continue
        if _column_exists(conn, table, "item"):
            raise AssertionError(
                "shepherd_internal_key_remains: rehearse the Shepherd public-ref migration"
            )
        rows = conn.execute(
            f"SELECT s.id FROM {table} s LEFT JOIN items i "
            "ON EXISTS (SELECT 1 FROM projects p WHERE p.id = i.project_id "
            "AND p.public_item_prefix || '-' || CAST(i.project_sequence AS TEXT) = s.public_ref) "
            "WHERE i.id IS NULL"
        ).fetchall()
        if rows:
            raise AssertionError(
                "shepherd_public_ref_unresolved: inspect the item identity mapping "
                "on the current serving build, repair it, and rehearse again"
            )
