"""QA reads and writes that hold on a database still converging new columns.

The deployment engine runs in-process against the authoritative database
before the release that adds a column boots and converges it, so a run
started from new source reads and writes QA rows on the previous release's
schema. Every statement naming a column added this way goes through here: a
read selects NULL for a column the database lacks, and a write leaves out a
value it has nowhere to store, so the run proceeds instead of refusing.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

STARTING_STATE_COLUMNS = ("starting_state", "starting_state_reason")


def present_columns(conn: Any, table: str) -> set[str]:
    from yoke_core.domain.schema_common import _get_columns

    return set(_get_columns(conn, table))


def converged_select(
    conn: Any, table: str, fields: Iterable[str], alias: str = ""
) -> str:
    """Select each field, or NULL for a column this database has not gained."""
    present = present_columns(conn, table)
    prefix = f"{alias}." if alias else ""
    return ",".join(
        f"{prefix}{field}" if field in present else f"NULL AS {field}"
        for field in fields
    )


def converged_values(conn: Any, table: str, values: Mapping[str, Any]) -> dict:
    """The column values this database can store, in their given order.

    Only the converging columns may be dropped: any other absent column is a
    real schema defect and is left in so the write refuses by name.
    """
    present = present_columns(conn, table)
    return {
        column: value
        for column, value in values.items()
        if column in present or column not in STARTING_STATE_COLUMNS
    }


__all__ = [
    "STARTING_STATE_COLUMNS",
    "converged_select",
    "converged_values",
    "present_columns",
]
