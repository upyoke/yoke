"""Persist the selected launch surface separately from the request."""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.migration_serving_version import NEXT_RELEASE
from yoke_core.domain.schema_common import (
    _add_column_if_not_exists,
    _column_exists,
    _column_is_not_null,
    _get_check_constraint_defs,
    _get_column_default,
    _table_exists,
)
from yoke_core.domain.session_launch_surface_domain import (
    LAUNCH_SURFACES,
    LAUNCH_SURFACE_VALUES_SQL,
    SELECTED_SURFACE_COLUMN_DDL,
)


MINIMUM_SERVING_VERSION = NEXT_RELEASE
TABLE = "session_launches"


def _marker(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _invalid_values(conn: Any, column: str) -> tuple[str, ...]:
    marker = _marker(conn)
    slots = ", ".join(marker for _ in LAUNCH_SURFACES)
    rows = conn.execute(
        f"SELECT DISTINCT {column} FROM {TABLE} "
        f"WHERE {column} IS NULL OR {column} NOT IN ({slots}) "
        f"ORDER BY {column}",
        LAUNCH_SURFACES,
    ).fetchall()
    return tuple("NULL" if row[0] is None else str(row[0]) for row in rows)


def _require_valid_values(conn: Any, column: str) -> None:
    invalid = _invalid_values(conn, column)
    if invalid:
        raise AssertionError(
            f"{TABLE}.{column} contains unsupported values: {list(invalid)}"
        )


def _constraint_covers(definition: str, column: str) -> bool:
    lowered = definition.lower()
    return column in lowered and all(surface in lowered for surface in LAUNCH_SURFACES)


def _ensure_postgres_constraint(conn: Any, column: str) -> None:
    if not db_backend.connection_is_postgres(conn):
        return
    checks = _get_check_constraint_defs(conn, TABLE)
    if any(_constraint_covers(definition, column) for definition in checks):
        return
    conn.execute(
        f"ALTER TABLE {TABLE} ADD CONSTRAINT {TABLE}_{column}_check "
        f"CHECK({column} IN ({LAUNCH_SURFACE_VALUES_SQL}))"
    )


def apply(conn: Any) -> None:
    if not _table_exists(conn, TABLE):
        return
    _require_valid_values(conn, "requested_surface")
    added = not _column_exists(conn, TABLE, "selected_surface")
    if added:
        default_surface = LAUNCH_SURFACES[0]
        ddl = SELECTED_SURFACE_COLUMN_DDL.replace(
            "TEXT NOT NULL", f"TEXT NOT NULL DEFAULT '{default_surface}'", 1
        )
        _add_column_if_not_exists(conn, TABLE, "selected_surface", ddl)
        conn.execute(f"UPDATE {TABLE} SET selected_surface=requested_surface")
    _require_valid_values(conn, "selected_surface")
    if db_backend.connection_is_postgres(conn):
        conn.execute(f"ALTER TABLE {TABLE} ALTER COLUMN selected_surface SET NOT NULL")
        conn.execute(f"ALTER TABLE {TABLE} ALTER COLUMN selected_surface DROP DEFAULT")
    _ensure_postgres_constraint(conn, "requested_surface")
    _ensure_postgres_constraint(conn, "selected_surface")


def invariants(conn: Any) -> None:
    assert _table_exists(conn, TABLE), "session launches table is missing"
    assert _column_exists(conn, TABLE, "selected_surface"), (
        "selected launch surface is missing"
    )
    assert _column_is_not_null(conn, TABLE, "selected_surface"), (
        "selected launch surface must be NOT NULL"
    )
    _require_valid_values(conn, "requested_surface")
    _require_valid_values(conn, "selected_surface")
    checks = _get_check_constraint_defs(conn, TABLE)
    assert any(
        _constraint_covers(definition, "selected_surface") for definition in checks
    ), "selected launch surface must constrain the supported vocabulary"
    if db_backend.connection_is_postgres(conn):
        assert _get_column_default(conn, TABLE, "selected_surface") is None, (
            "selected launch surface must not have an implicit default"
        )
        assert any(
            _constraint_covers(definition, "requested_surface") for definition in checks
        ), "requested launch surface must constrain the supported vocabulary"


__all__ = ["apply", "invariants"]
