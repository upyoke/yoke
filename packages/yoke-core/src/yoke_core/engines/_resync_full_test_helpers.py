"""Shared module-level helpers and pytest fixtures for resync_full test files.

Underscore prefix keeps pytest from collecting this as a test module.
Used by test_resync_full.py and its split siblings.

The two pytest fixtures (`test_db`, `populated_db`) are shared across
splits to avoid 5x duplication of ~95 lines of schema + seed SQL; the
alternative was substantial schema duplication that would risk drift
across split files.
"""

from __future__ import annotations

from typing import Dict, List

import pytest

from yoke_core.domain import db_backend
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


def _apply_resync_full_schema() -> None:
    conn = db_backend.connect()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY,
                title TEXT,
                status TEXT,
                priority TEXT,
                type TEXT,
                source TEXT,
                owner TEXT,
                spec TEXT,
                frozen INTEGER DEFAULT 0,
                blocked INTEGER DEFAULT 0,
                blocked_reason TEXT,
                github_issue TEXT,
                project_id INTEGER DEFAULT 1,
                project_sequence INTEGER
            )
        """)
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
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY,
                slug TEXT UNIQUE,
                name TEXT,
                default_branch TEXT,
                created_at TEXT,
                github_repo TEXT,
                public_item_prefix TEXT DEFAULT 'YOK'
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY,
                event_id TEXT UNIQUE,
                event_name TEXT,
                event_type TEXT,
                item_id TEXT,
                envelope TEXT,
                created_at TEXT,
                source_type TEXT,
                session_id TEXT DEFAULT '',
                severity TEXT DEFAULT 'INFO',
                event_kind TEXT DEFAULT 'lifecycle',
                event_outcome TEXT
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
            "INSERT INTO projects "
            "(id, slug, name, default_branch, created_at, "
            "github_repo, public_item_prefix) "
            "VALUES (1, 'yoke', 'Yoke', 'main', "
            "'2026-01-01T00:00:00Z', 'upyoke/yoke', 'YOK')"
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def test_db(tmp_path):
    """Create a temporary DB with items, epic_tasks, projects, events tables."""
    with init_test_db(tmp_path, apply_schema=_apply_resync_full_schema) as db_path:
        yield db_path


@pytest.fixture
def populated_db(test_db):
    """DB with test items for comparison tests."""
    conn = connect_test_db(test_db)
    conn.execute("""
        INSERT INTO items (id, title, status, priority, type, source, spec, frozen, github_issue, project_id, project_sequence)
        VALUES (42, 'Test item', 'implementing', 'high', 'issue', 'manual', 'Item body', 0, '#100', 1, 42)
    """)
    conn.execute("""
        INSERT INTO items (id, title, status, priority, type, source, spec, frozen, github_issue, project_id, project_sequence)
        VALUES (43, 'Done item', 'done', 'medium', 'issue', 'auto', 'Done body', 0, '#101', 1, 43)
    """)
    conn.execute("""
        INSERT INTO items (id, title, status, priority, type, source, spec, frozen, github_issue, project_id, project_sequence)
        VALUES (1246, 'Epic parent', 'implementing', 'high', 'epic', 'manual', 'Epic body', 0, '#102', 1, 1246)
    """)
    conn.execute("""
        INSERT INTO epic_tasks (epic_id, task_num, title, status, body, github_issue)
        VALUES ('1246', 1, 'Task one', 'implementing', 'Task body', '#200')
    """)
    conn.execute("""
        INSERT INTO items (id, title, status, priority, type, source, spec, frozen, github_issue, project_id, project_sequence)
        VALUES (45, 'Cancelled item', 'cancelled', 'low', 'issue', 'manual', 'Cancel body', 0, '#103', 1, 45)
    """)
    conn.execute("""
        INSERT INTO items (id, title, status, priority, type, source, spec, frozen, github_issue, project_id, project_sequence)
        VALUES (46, 'Release item', 'release', 'high', 'issue', 'manual', 'Release body', 0, '#104', 1, 46)
    """)
    conn.execute("""
        INSERT INTO items (id, title, status, priority, type, source, spec, frozen, github_issue, project_id, project_sequence)
        VALUES (47, 'Frozen item', 'implementing', 'high', 'issue', 'manual', 'Frozen body', 1, '#105', 1, 47)
    """)
    conn.commit()
    conn.close()
    return test_db


def _make_gh_issues(items: List[Dict]) -> Dict[str, Dict[int, Dict]]:
    """Build gh_by_project from a list of issue dicts."""
    result: Dict[str, Dict[int, Dict]] = {"yoke": {}}
    for item in items:
        result["yoke"][item["number"]] = item
    return result
