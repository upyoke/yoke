"""Drop the retired ``items.shepherd_log`` column.

Shepherd records each verdict as a row in ``shepherd_verdicts``; the item
read, the item page and the rendered body all read that table. Nothing has
written ``items.shepherd_log`` since verdicts moved there, so its stored text
is a stale copy of history the verdict rows already hold. A build that
predates this entry still selects the column, so the entry declares the
oldest build that may serve against it.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.migration_serving_version import NEXT_RELEASE
from yoke_core.domain.schema_common import _column_exists, _table_exists


MINIMUM_SERVING_VERSION = NEXT_RELEASE
TABLE = "items"
RETIRED_COLUMN = "shepherd_log"


def apply(conn: Any) -> None:
    """Drop the column wherever it is still present."""
    if not _table_exists(conn, TABLE) or not _column_exists(
        conn, TABLE, RETIRED_COLUMN
    ):
        return
    conn.execute(f'ALTER TABLE "{TABLE}" DROP COLUMN "{RETIRED_COLUMN}"')


def invariants(conn: Any) -> None:
    """Prove the retired column is gone."""
    if not _table_exists(conn, TABLE):
        return
    assert not _column_exists(conn, TABLE, RETIRED_COLUMN), (
        f"{TABLE}.{RETIRED_COLUMN} remains after the drop"
    )


__all__ = [
    "MINIMUM_SERVING_VERSION",
    "RETIRED_COLUMN",
    "TABLE",
    "apply",
    "invariants",
]
