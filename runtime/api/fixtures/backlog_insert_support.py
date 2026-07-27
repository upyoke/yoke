"""Shared SQL helpers for disposable backlog fixture inserts."""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.project_identity import (
    DEFAULT_PUBLIC_ITEM_PREFIX,
    resolve_project,
)
from yoke_core.domain.project_seed_test_helpers import SEED_PROJECT_IDS
from yoke_core.domain.schema_common import _column_exists


def now() -> str:
    return iso8601_now()


def placeholder(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def table_has_column(conn: Any, table: str, column: str) -> bool:
    try:
        return _column_exists(conn, table, column)
    except Exception:
        return False


def ensure_project_id(conn: Any, project: str, *, ts: str) -> int:
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
            ts,
        ),
    )
    return project_id
