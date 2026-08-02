"""Drop the retired session-report storage after a row-count checkpoint."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.schema_common import _table_exists


TABLE_NAME = "wrapup_reports"
EXPECTED_ROW_COUNT = 59


def _row_count(conn: Any) -> int:
    return int(conn.execute(f'SELECT COUNT(*) FROM "{TABLE_NAME}"').fetchone()[0])


def apply(conn: Any) -> None:
    """Drop the retired table only when its expected historical shape is intact."""
    if not _table_exists(conn, TABLE_NAME):
        raise AssertionError(f"{TABLE_NAME} table is missing")
    actual_count = _row_count(conn)
    if actual_count != EXPECTED_ROW_COUNT:
        raise AssertionError(
            f"{TABLE_NAME} expected {EXPECTED_ROW_COUNT} rows, found {actual_count}"
        )
    conn.execute(f'DROP TABLE "{TABLE_NAME}"')


def invariants(conn: Any) -> None:
    """Verify that the retired table no longer exists."""
    if _table_exists(conn, TABLE_NAME):
        raise AssertionError(f"{TABLE_NAME} table still exists")


__all__ = ["EXPECTED_ROW_COUNT", "TABLE_NAME", "apply", "invariants"]
