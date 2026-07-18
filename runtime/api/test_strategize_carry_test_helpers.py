"""Shared helpers for strategize-carry tests.

Imported by ``test_strategize_carry.py`` and
``test_strategize_carry_summary.py``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.strategize_carry import ensure_schema
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl


PROJECTS_DDL = """
CREATE TABLE projects (
    id INTEGER PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    public_item_prefix TEXT NOT NULL DEFAULT 'YOK',
    created_at TEXT NOT NULL DEFAULT '2026-01-01T00:00:00Z'
);
INSERT INTO projects (id, slug, name, public_item_prefix, created_at)
VALUES
    (1, 'yoke', 'Yoke', 'YOK', '2026-01-01T00:00:00Z'),
    (2, 'externalwebapp', 'ExternalWebapp', 'EXT', '2026-01-01T00:00:00Z');
"""


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _make_db() -> Any:
    from runtime.api.fixtures.pg_testdb import (
        connect_test_database,
        create_test_database,
        drop_database_on_close,
    )

    db_name = create_test_database()
    conn = connect_test_database(db_name)
    apply_fixture_ddl(conn, PROJECTS_DDL)
    conn.execute(
        """
        CREATE TABLE items (
            id INTEGER PRIMARY KEY,
            title TEXT,
            priority TEXT DEFAULT 'medium',
            project_id INTEGER DEFAULT 1,
            project_sequence INTEGER,
            merged_at TEXT
        )
        """
    )
    ensure_schema(conn)
    conn.commit()
    return drop_database_on_close(conn, db_name)


def _seed_landed_items(
    conn: Any,
    *,
    count: int,
    project: str = "yoke",
    days_ago: int = 5,
    priority: str = "medium",
    start_id: int = 1,
    title_prefix: str = "Landed",
) -> list[int]:
    """Insert ``count`` items with merged_at ``days_ago`` days before now."""
    now = datetime.now(timezone.utc)
    merged = now - timedelta(days=days_ago)
    ids: list[int] = []
    p = _p(conn)
    project_id = 2 if project == "externalwebapp" else 1
    for offset in range(count):
        item_id = start_id + offset
        conn.execute(
            "INSERT INTO items (id, title, priority, project_id, project_sequence, merged_at) "
            f"VALUES ({p}, {p}, {p}, {p}, {p}, {p})",
            (
                item_id,
                f"{title_prefix} {item_id}",
                priority,
                project_id,
                item_id,
                _iso(merged),
            ),
        )
        ids.append(item_id)
    conn.commit()
    return ids
