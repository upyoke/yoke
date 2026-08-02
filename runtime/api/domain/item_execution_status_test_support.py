"""Database setup for item execution-status projection tests."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from runtime.api.fixtures.file_test_db import init_test_db
from yoke_core.domain import db_backend
from yoke_core.domain.schema_init_apply import execute_schema_script

NOW = datetime(2026, 5, 8, 12, 0, 0, tzinfo=timezone.utc)

CORE_SCHEMA = """
CREATE TABLE projects (id INTEGER PRIMARY KEY, slug TEXT UNIQUE, name TEXT, public_item_prefix TEXT DEFAULT 'YOK');
CREATE TABLE items (id INTEGER PRIMARY KEY, title TEXT NOT NULL,
    status TEXT DEFAULT 'idea',
    project_id INTEGER DEFAULT 1, project_sequence INTEGER NOT NULL, spec TEXT);
CREATE TABLE item_worktrees (id INTEGER PRIMARY KEY,
    item_id INTEGER NOT NULL, branch TEXT NOT NULL, path TEXT,
    lane_role TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, released_at TEXT);
CREATE TABLE work_claims (id INTEGER PRIMARY KEY, session_id TEXT,
    target_kind TEXT, item_id INTEGER, claim_type TEXT,
    claimed_at TEXT, last_heartbeat TEXT, released_at TEXT);
CREATE TABLE path_claims (id INTEGER PRIMARY KEY, state TEXT,
    blocked_reason TEXT, owner_kind TEXT, owner_item_id INTEGER);
CREATE TABLE item_sections (item_id INTEGER, section_name TEXT,
    content TEXT, updated_at TEXT, PRIMARY KEY (item_id, section_name));
CREATE TABLE item_status_transitions (id INTEGER PRIMARY KEY,
    item_id INTEGER NOT NULL, task_num INTEGER, from_status TEXT,
    to_status TEXT NOT NULL, source TEXT, session_id TEXT,
    actor_id INTEGER, project_id INTEGER, created_at TEXT NOT NULL);
"""


def apply_core_schema() -> None:
    """Build the execution-status schema on the resolved test database."""
    conn = db_backend.connect()
    try:
        execute_schema_script(conn, CORE_SCHEMA)
        from yoke_core.domain.workflow_registry import converge_builtin_workflows
        from yoke_core.domain.workflow_schema import ensure_workflow_schema

        ensure_workflow_schema(conn)
        converge_builtin_workflows(conn)
        conn.execute(
            "INSERT INTO projects (id, slug, name, public_item_prefix) VALUES (1, 'yoke', 'Yoke', 'YOK')"
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def core_db(tmp_path):
    with init_test_db(tmp_path, apply_schema=apply_core_schema) as db_path:
        yield db_path


def add_item(conn, item_id, **kwargs) -> None:
    p = "%s"
    cols = {
        "title": "Test",
        "workflow_id": "issue",
        "status": "implementing",
        "project_id": 1,
        "project_sequence": item_id,
        "worktree": None,
        "spec": None,
    }
    cols.update(kwargs)
    from yoke_core.domain.workflow_registry import resolve_current_workflow_pin

    _, version_id = resolve_current_workflow_pin(conn, cols["workflow_id"])
    worktree = cols.pop("worktree", None)
    fields = ("title", "status", "project_id", "project_sequence", "spec")
    conn.execute(
        "INSERT INTO items(id, title, status, project_id, "
        "project_sequence, spec, workflow_id, workflow_version_id)"
        f" VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})",
        (item_id, *(cols[f] for f in fields), cols["workflow_id"], version_id),
    )
    if worktree:
        conn.execute(
            "INSERT INTO item_worktrees "
            "(item_id, branch, lane_role, state, created_at, updated_at) "
            f"VALUES ({p}, {p}, 'implementation', 'active', {p}, {p})",
            (
                item_id,
                worktree,
                "2026-05-08T12:00:00Z",
                "2026-05-08T12:00:00Z",
            ),
        )
    conn.commit()
