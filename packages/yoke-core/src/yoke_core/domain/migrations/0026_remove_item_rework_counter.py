"""Remove the item column that never represented reliable rework data."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.migration_serving_version import NEXT_RELEASE
from yoke_core.domain.schema_common import _column_exists, _table_exists


MINIMUM_SERVING_VERSION = NEXT_RELEASE
TABLE = "items"
RETIRED_COLUMN = "rework_count"


def apply(conn: Any) -> None:
    """Drop the retired column when an older database still carries it."""
    if not _table_exists(conn, TABLE) or not _column_exists(
        conn, TABLE, RETIRED_COLUMN
    ):
        return
    conn.execute(f'ALTER TABLE "{TABLE}" DROP COLUMN "{RETIRED_COLUMN}"')


def invariants(conn: Any) -> None:
    """Prove that the retired column is absent wherever the table exists."""
    if _table_exists(conn, TABLE):
        assert not _column_exists(conn, TABLE, RETIRED_COLUMN), (
            f"{TABLE}.{RETIRED_COLUMN} must be absent after convergence"
        )


__all__ = [
    "MINIMUM_SERVING_VERSION",
    "RETIRED_COLUMN",
    "TABLE",
    "apply",
    "invariants",
]
