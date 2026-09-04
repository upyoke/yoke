"""Persist explicit and machine-resolved session launch selections."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.migration_serving_version import NEXT_RELEASE
from yoke_core.domain.schema_common import (
    _add_column_if_not_exists,
    _column_exists,
    _table_exists,
)


MINIMUM_SERVING_VERSION = NEXT_RELEASE
TABLE_COLUMNS = {
    "session_launches": (
        ("requested_reasoning_effort", "TEXT DEFAULT NULL"),
        ("requested_context_window_tokens", "INTEGER DEFAULT NULL"),
        ("resolved_reasoning_effort", "TEXT DEFAULT NULL"),
        ("resolved_context_window_tokens", "INTEGER DEFAULT NULL"),
    ),
    "session_relays": (("preferred_session_reasoning_efforts", "TEXT DEFAULT NULL"),),
}


def apply(conn: Any) -> None:
    """Add nullable selection facts without disturbing existing rows."""
    for table, columns in TABLE_COLUMNS.items():
        if not _table_exists(conn, table):
            continue
        for column, ddl in columns:
            _add_column_if_not_exists(conn, table, column, ddl)


def invariants(conn: Any) -> None:
    """Prove every model-selection column is present after apply."""
    for table, columns in TABLE_COLUMNS.items():
        if not _table_exists(conn, table):
            continue
        for column, _ddl in columns:
            assert _column_exists(conn, table, column), (
                f"{table}.{column} is missing after model-selection convergence"
            )


__all__ = ["MINIMUM_SERVING_VERSION", "TABLE_COLUMNS", "apply", "invariants"]
