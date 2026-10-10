"""Shared SQL helpers for disposable backlog fixture inserts."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from yoke_core.domain import db_backend
from yoke_contracts.timestamps import parse_instant
from yoke_core.domain.db_helpers import instant_parameter, utc_now
from yoke_core.domain.stored_instant_columns import STORED_INSTANT_COLUMNS
from yoke_core.domain.project_identity import (
    DEFAULT_PUBLIC_ITEM_PREFIX,
    resolve_project,
)
from yoke_core.domain.project_seed_test_helpers import SEED_PROJECT_IDS
from yoke_core.domain.schema_common import _column_exists


_INSTANT_COLUMNS = frozenset(STORED_INSTANT_COLUMNS)


def now() -> datetime:
    return parse_instant(utc_now())


def stamp(value: str | datetime | None) -> datetime:
    return now() if value is None else parse_instant(value)


def native_columns(table: str, columns: dict[str, Any]) -> dict[str, Any]:
    """Parse finite declared clocks; unrelated fixture values remain opaque."""
    return {
        key: parse_instant(value)
        if (table, key) in _INSTANT_COLUMNS and value is not None
        else value
        for key, value in columns.items()
    }


def values(conn: Any, table: str, columns: dict[str, Any]) -> tuple[Any, ...]:
    native = native_columns(table, columns)
    return tuple(
        instant_parameter(conn, value) if (table, key) in _INSTANT_COLUMNS else value
        for key, value in native.items()
    )


def placeholder(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def table_has_column(conn: Any, table: str, column: str) -> bool:
    try:
        return _column_exists(conn, table, column)
    except Exception:
        return False


def ensure_project_id(conn: Any, project: str, *, ts: datetime) -> int:
    """Return numeric project authority, creating a lightweight row if needed."""
    ident = resolve_project(conn, project, required=False)
    if ident is not None:
        return ident.id
    slug = str(project)
    project_id = int(slug) if slug.isdigit() else SEED_PROJECT_IDS.get(slug)
    p = placeholder(conn)
    if project_id is None:
        row = conn.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM projects").fetchone()
        project_id = int(row[0])
    if slug.isdigit():
        slug = str(project_id)
    conn.execute(
        "INSERT INTO projects "
        "(id, slug, name, public_item_prefix, created_at) "
        f"VALUES ({p}, {p}, {p}, {p}, {p}) "
        "ON CONFLICT (id) DO NOTHING",
        (
            project_id,
            slug,
            slug,
            DEFAULT_PUBLIC_ITEM_PREFIX,
            instant_parameter(conn, ts),
        ),
    )
    return project_id
