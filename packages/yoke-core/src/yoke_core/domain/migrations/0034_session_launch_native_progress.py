"""Add durable native-process progress to session launch attempts."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.migration_serving_version import NEXT_RELEASE
from yoke_core.domain.schema_common import (
    _add_column_if_not_exists,
    _column_exists,
    _table_exists,
)


MINIMUM_SERVING_VERSION = NEXT_RELEASE
TABLE = "session_launches"
COLUMNS = (
    ("native_launch_pid", "INTEGER DEFAULT NULL"),
    ("native_launch_phase", "TEXT DEFAULT NULL"),
    ("native_launch_observed_at", "TEXT DEFAULT NULL"),
    ("spawn_duration_ms", "INTEGER DEFAULT NULL"),
)


def apply(conn: Any) -> None:
    """Add nullable telemetry without disturbing existing launch rows."""
    if not _table_exists(conn, TABLE):
        return
    for column, ddl in COLUMNS:
        _add_column_if_not_exists(conn, TABLE, column, ddl)


def invariants(conn: Any) -> None:
    """Prove every native-process telemetry column is present after apply."""
    if not _table_exists(conn, TABLE):
        return
    for column, _ddl in COLUMNS:
        assert _column_exists(conn, TABLE, column), (
            f"{TABLE}.{column} is missing after native progress convergence"
        )


__all__ = ["COLUMNS", "MINIMUM_SERVING_VERSION", "TABLE", "apply", "invariants"]
