"""Store every QA method prerequisite as one canonical capability set."""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import (
    _add_column_if_not_exists,
    _column_exists,
    _table_exists,
)


MINIMUM_SERVING_VERSION = "0.1.1+launch.243"
_RETIRED_COLUMN = "required_capability_kind"
_SET_COLUMN = "required_capability_kinds"
_NON_ARRAY_REQUIREMENT_VALUES = {
    "browser-qa": ("browser-qa",),
    # Repo access is implicit in checkout-backed review; it is not a
    # registered project capability and therefore declares no prerequisite.
    '{"repo":true}': (),
}


def _marker(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _value(row: Any, key: str, position: int) -> Any:
    return row[key] if hasattr(row, "keys") else row[position]


def _capability_kinds(value: Any, *, subject: str) -> tuple[str, ...]:
    """Decode one strict capability array without importing cutover code."""
    decoded = value
    if value is None:
        decoded = []
    elif isinstance(value, str):
        try:
            decoded = json.loads(value)
        except ValueError as exc:
            raise ValueError(
                f"{subject} required capability kinds must be a JSON array"
            ) from exc
    if isinstance(decoded, (str, bytes, dict)) or not isinstance(
        decoded, Iterable
    ):
        raise ValueError(f"{subject} required capability kinds must be an array")
    kinds: list[str] = []
    for raw in decoded:
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError(
                f"{subject} required capability kinds must be non-empty strings"
            )
        kinds.append(raw.strip())
    return tuple(sorted(set(kinds)))


def _encode(values: Any) -> str:
    return json.dumps(list(_capability_kinds(values, subject="capability set")))


def _migrate_methods(conn: Any) -> None:
    if not _table_exists(conn, "qa_methods"):
        return
    _add_column_if_not_exists(
        conn,
        "qa_methods",
        _SET_COLUMN,
        "TEXT NOT NULL DEFAULT '[]'",
    )
    if not _column_exists(conn, "qa_methods", _RETIRED_COLUMN):
        return
    marker = _marker(conn)
    rows = conn.execute(
        f'SELECT id,"{_RETIRED_COLUMN}","{_SET_COLUMN}" FROM qa_methods'
    ).fetchall()
    for row in rows:
        retired = _value(row, _RETIRED_COLUMN, 1)
        current = _value(row, _SET_COLUMN, 2)
        values = _capability_kinds(
            current,
            subject=f"method {_value(row, 'id', 0)!r}",
        )
        if retired not in (None, ""):
            values = (*values, str(retired))
        conn.execute(
            f'UPDATE qa_methods SET "{_SET_COLUMN}"={marker} WHERE id={marker}',
            (_encode(values), _value(row, "id", 0)),
        )
    conn.execute(f'ALTER TABLE qa_methods DROP COLUMN "{_RETIRED_COLUMN}"')


def _migrate_requirements(conn: Any) -> None:
    if not _table_exists(conn, "qa_requirements"):
        return
    _add_column_if_not_exists(
        conn,
        "qa_requirements",
        "capability_requirements",
        "TEXT",
    )
    if not _column_exists(conn, "qa_requirements", _RETIRED_COLUMN):
        return
    marker = _marker(conn)
    rows = conn.execute(
        f'SELECT id,"{_RETIRED_COLUMN}",capability_requirements FROM qa_requirements'
    ).fetchall()
    for row in rows:
        retired = _value(row, _RETIRED_COLUMN, 1)
        raw_existing = _value(row, "capability_requirements", 2)
        existing = _NON_ARRAY_REQUIREMENT_VALUES.get(raw_existing)
        if existing is None:
            existing = _capability_kinds(
                raw_existing,
                subject=f"QA requirement {_value(row, 'id', 0)}",
            )
        values = existing
        if retired not in (None, ""):
            values = (*values, str(retired))
        if raw_existing is None and retired in (None, ""):
            continue
        conn.execute(
            f"UPDATE qa_requirements SET capability_requirements={marker} "
            f"WHERE id={marker}",
            (_encode(values), _value(row, "id", 0)),
        )
    conn.execute(f'ALTER TABLE qa_requirements DROP COLUMN "{_RETIRED_COLUMN}"')


def apply(conn: Any) -> None:
    _migrate_methods(conn)
    _migrate_requirements(conn)


def invariants(conn: Any) -> None:
    if _table_exists(conn, "qa_methods"):
        if _column_exists(conn, "qa_methods", _RETIRED_COLUMN):
            raise AssertionError("qa_methods retains the retired capability column")
        if not _column_exists(conn, "qa_methods", _SET_COLUMN):
            raise AssertionError("qa_methods capability-set column is absent")
        for row in conn.execute(
            f'SELECT id,"{_SET_COLUMN}" FROM qa_methods'
        ).fetchall():
            _capability_kinds(
                _value(row, _SET_COLUMN, 1),
                subject=f"method {_value(row, 'id', 0)!r}",
            )
    if _table_exists(conn, "qa_requirements"):
        if _column_exists(conn, "qa_requirements", _RETIRED_COLUMN):
            raise AssertionError(
                "qa_requirements retains the retired capability column"
            )
        for row in conn.execute(
            "SELECT id,capability_requirements FROM qa_requirements "
            "WHERE capability_requirements IS NOT NULL"
        ).fetchall():
            _capability_kinds(
                _value(row, "capability_requirements", 1),
                subject=f"QA requirement {_value(row, 'id', 0)}",
            )


__all__ = ["MINIMUM_SERVING_VERSION", "apply", "invariants"]
