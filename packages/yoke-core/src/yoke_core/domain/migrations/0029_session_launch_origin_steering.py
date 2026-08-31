"""Admit steering as a live launch origin on existing origin CHECK constraints."""

from __future__ import annotations

import re
from typing import Any

from yoke_contracts.session_control.launch_origin import (
    LAUNCH_ORIGINS,
    LAUNCH_ORIGIN_VALUES_SQL,
)
from yoke_core.domain import db_backend
from yoke_core.domain.migration_serving_version import NEXT_RELEASE
from yoke_core.domain.schema_common import _column_exists, _table_exists


MINIMUM_SERVING_VERSION = NEXT_RELEASE
TABLE = "session_launches"
COLUMN = "origin"
CONSTRAINT = "session_launches_origin_check"
_QUOTED = re.compile(r"'([^']+)'")


def _marker(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _invalid_values(conn: Any) -> tuple[str, ...]:
    marker = _marker(conn)
    slots = ", ".join(marker for _ in LAUNCH_ORIGINS)
    rows = conn.execute(
        f"SELECT DISTINCT {COLUMN} FROM {TABLE} "
        f"WHERE {COLUMN} IS NULL OR {COLUMN} NOT IN ({slots}) "
        f"ORDER BY {COLUMN}",
        LAUNCH_ORIGINS,
    ).fetchall()
    return tuple("NULL" if row[0] is None else str(row[0]) for row in rows)


def _require_valid_values(conn: Any) -> None:
    invalid = _invalid_values(conn)
    if invalid:
        raise AssertionError(
            f"{TABLE}.{COLUMN} contains unsupported values: {list(invalid)}"
        )


def _origin_check_rows(conn: Any) -> list[tuple[str, str]]:
    rows = conn.execute(
        "SELECT con.conname, pg_get_constraintdef(con.oid) "
        "FROM pg_constraint con "
        "JOIN pg_class rel ON rel.oid=con.conrelid "
        "JOIN pg_namespace ns ON ns.oid=rel.relnamespace "
        "WHERE ns.nspname=current_schema() AND rel.relname=%s "
        "AND con.contype='c'",
        (TABLE,),
    ).fetchall()
    found: list[tuple[str, str]] = []
    for row in rows:
        name, definition = str(row[0]), str(row[1])
        if COLUMN in definition.lower():
            found.append((name, definition))
    return found


def _quoted_values(definition: str) -> set[str]:
    return set(_QUOTED.findall(definition))


def apply(conn: Any) -> None:
    if not _table_exists(conn, TABLE) or not _column_exists(conn, TABLE, COLUMN):
        return
    _require_valid_values(conn)
    if not db_backend.connection_is_postgres(conn):
        return
    checks = _origin_check_rows(conn)
    desired = set(LAUNCH_ORIGINS)
    if len(checks) == 1 and _quoted_values(checks[0][1]) == desired:
        return
    for name, _definition in checks:
        escaped = name.replace('"', '""')
        conn.execute(f'ALTER TABLE "{TABLE}" DROP CONSTRAINT "{escaped}"')
    conn.execute(
        f"ALTER TABLE {TABLE} ADD CONSTRAINT {CONSTRAINT} "
        f"CHECK({COLUMN} IN ({LAUNCH_ORIGIN_VALUES_SQL}))"
    )


def invariants(conn: Any) -> None:
    assert _table_exists(conn, TABLE), "session launches table is missing"
    assert _column_exists(conn, TABLE, COLUMN), "launch origin column is missing"
    _require_valid_values(conn)
    if not db_backend.connection_is_postgres(conn):
        return
    checks = _origin_check_rows(conn)
    desired = set(LAUNCH_ORIGINS)
    assert any(_quoted_values(definition) == desired for _name, definition in checks), (
        "launch origin must constrain operator and steering"
    )


__all__ = ["MINIMUM_SERVING_VERSION", "apply", "invariants"]
