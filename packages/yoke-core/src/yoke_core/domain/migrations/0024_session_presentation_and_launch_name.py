"""Add observed session presentation and structured launch display names."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.migration_serving_version import NEXT_RELEASE
from yoke_core.domain.schema_common import (
    _add_column_if_not_exists,
    _column_exists,
    _table_exists,
)


MINIMUM_SERVING_VERSION = NEXT_RELEASE

_PRESENTATION_COLUMNS = (
    ("presentation_surface", "TEXT DEFAULT NULL"),
    ("presentation_state", "TEXT DEFAULT NULL"),
    ("presentation_mode", "TEXT DEFAULT NULL"),
    ("presentation_source", "TEXT DEFAULT NULL"),
    ("presentation_observed_at", "TEXT DEFAULT NULL"),
)


def apply(conn: Any) -> None:
    if _table_exists(conn, "harness_sessions"):
        for column, ddl in _PRESENTATION_COLUMNS:
            _add_column_if_not_exists(conn, "harness_sessions", column, ddl)
    if _table_exists(conn, "session_launches"):
        _add_column_if_not_exists(
            conn,
            "session_launches",
            "session_name",
            "TEXT DEFAULT NULL",
        )


def invariants(conn: Any) -> None:
    if _table_exists(conn, "harness_sessions"):
        for column, _ddl in _PRESENTATION_COLUMNS:
            assert _column_exists(conn, "harness_sessions", column)
    if _table_exists(conn, "session_launches"):
        assert _column_exists(conn, "session_launches", "session_name")


__all__ = ["MINIMUM_SERVING_VERSION", "apply", "invariants"]
