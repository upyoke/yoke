"""Add permanent session termination state and native-reap requests."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.migration_serving_version import NEXT_RELEASE
from yoke_core.domain.schema_common import (
    _add_column_if_not_exists,
    _column_exists,
    _table_exists,
)
from yoke_core.domain.session_control_schema import create_session_control_tables


MINIMUM_SERVING_VERSION = NEXT_RELEASE
TABLE = "harness_sessions"
TERMINATION_COLUMNS = (
    ("terminated_at", "TEXT DEFAULT NULL"),
    ("terminated_by_actor_id", "INTEGER DEFAULT NULL"),
    ("terminated_by_session_id", "TEXT DEFAULT NULL"),
    ("termination_reason", "TEXT DEFAULT NULL"),
)


def apply(conn: Any) -> None:
    if not _table_exists(conn, TABLE):
        return
    for column, ddl in TERMINATION_COLUMNS:
        _add_column_if_not_exists(conn, TABLE, column, ddl)
    create_session_control_tables(conn)


def invariants(conn: Any) -> None:
    if not _table_exists(conn, TABLE):
        return
    for column, _ddl in TERMINATION_COLUMNS:
        assert _column_exists(conn, TABLE, column)
    assert _table_exists(conn, "session_termination_reaps")


__all__ = [
    "MINIMUM_SERVING_VERSION",
    "TABLE",
    "TERMINATION_COLUMNS",
    "apply",
    "invariants",
]
