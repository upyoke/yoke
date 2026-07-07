"""Shared module-level helpers and pytest fixtures for resync test files.

Underscore prefix keeps pytest from collecting this as a test module.
Used by test_resync.py and its split siblings.

The two pytest fixtures (`test_db`, `populated_db`) are shared across
splits to avoid duplicating ~80 lines of schema + seed SQL; sharing them
keeps the schema from drifting across split files.
"""

from __future__ import annotations

import pytest

from yoke_core.domain import db_backend
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from runtime.api.test_dependency_schema import ITEMS_SCHEMA, PROJECTS_SCHEMA


def _apply_resync_schema() -> None:
    conn = db_backend.connect()
    try:
        apply_fixture_ddl(conn, PROJECTS_SCHEMA + ITEMS_SCHEMA)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS epic_tasks (
                epic_id TEXT,
                task_num INTEGER,
                title TEXT,
                status TEXT,
                body TEXT,
                github_issue TEXT,
                PRIMARY KEY (epic_id, task_num)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY,
                event_name TEXT,
                event_type TEXT,
                item_id TEXT,
                envelope TEXT,
                created_at TEXT,
                source_type TEXT
            )
        """)
        # Empty path_claims so render_body's path-claims section read finds
        # the table and returns no rows instead of raising "no such table".
        conn.execute("""
            CREATE TABLE IF NOT EXISTS path_claims (
                id INTEGER PRIMARY KEY,
                item_id INTEGER,
                state TEXT
            )
        """)
        conn.execute(
            "UPDATE projects SET github_repo=%s WHERE slug='yoke'",
            ("upyoke/yoke",),
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def test_db(tmp_path):
    """Create a temporary DB with items and epic_tasks tables."""
    with init_test_db(tmp_path, apply_schema=_apply_resync_schema) as db_path:
        yield db_path


@pytest.fixture
def populated_db(test_db):
    """DB with some test items."""
    conn = connect_test_db(test_db)
    conn.execute("""
        INSERT INTO items
        (id, title, status, priority, type, source, spec, frozen,
         github_issue, project_id, project_sequence, created_at, updated_at)
        VALUES (42, 'Test item', 'implementing', 'high', 'issue', 'manual',
                'Item body', 0, '#100', 1, 42, '2026-01-01', '2026-01-01')
    """)
    conn.execute("""
        INSERT INTO items
        (id, title, status, priority, type, source, spec, frozen,
         github_issue, project_id, project_sequence, created_at, updated_at)
        VALUES (43, 'Done item', 'done', 'medium', 'issue', 'auto',
                'Done body', 0, '#101', 1, 43, '2026-01-01', '2026-01-01')
    """)
    conn.execute("""
        INSERT INTO items
        (id, title, status, priority, type, source, spec, frozen,
         github_issue, project_id, project_sequence, created_at, updated_at)
        VALUES (1246, 'Epic parent', 'implementing', 'high', 'epic',
                'manual', 'Epic body', 0, '#102', 1, 1246,
                '2026-01-01', '2026-01-01')
    """)
    conn.execute("""
        INSERT INTO epic_tasks (epic_id, task_num, title, status, body, github_issue)
        VALUES ('1246', 1, 'Task one', 'implementing', 'Task body', '#200')
    """)
    conn.commit()
    conn.close()
    return test_db
