"""Rename the parked-only reason into a mode-independent quiet reason."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.migration_serving_version import NEXT_RELEASE
from yoke_core.domain.schema_common import _column_exists, _table_exists


MINIMUM_SERVING_VERSION = NEXT_RELEASE
TABLE = "harness_sessions"
RETIRED_COLUMN = "parked_reason"
CURRENT_COLUMN = "quiet_reason"


def apply(conn: Any) -> None:
    """Preserve every reason while converging either pre-boot schema shape."""
    if not _table_exists(conn, TABLE) or not _column_exists(
        conn, TABLE, RETIRED_COLUMN
    ):
        return
    if _column_exists(conn, TABLE, CURRENT_COLUMN):
        conn.execute(
            f'UPDATE "{TABLE}" SET "{CURRENT_COLUMN}" = "{RETIRED_COLUMN}" '
            f'WHERE "{RETIRED_COLUMN}" IS NOT NULL'
        )
        conn.execute(f'ALTER TABLE "{TABLE}" DROP COLUMN "{RETIRED_COLUMN}"')
        return
    conn.execute(
        f'ALTER TABLE "{TABLE}" RENAME COLUMN "{RETIRED_COLUMN}" TO "{CURRENT_COLUMN}"'
    )


def invariants(conn: Any) -> None:
    """Prove the generic reason is the only live reason column."""
    if not _table_exists(conn, TABLE):
        return
    assert _column_exists(conn, TABLE, CURRENT_COLUMN), (
        f"{TABLE}.{CURRENT_COLUMN} is missing after quiet-reason convergence"
    )
    assert not _column_exists(conn, TABLE, RETIRED_COLUMN), (
        f"{TABLE}.{RETIRED_COLUMN} remains after quiet-reason convergence"
    )


__all__ = [
    "CURRENT_COLUMN",
    "MINIMUM_SERVING_VERSION",
    "RETIRED_COLUMN",
    "TABLE",
    "apply",
    "invariants",
]
