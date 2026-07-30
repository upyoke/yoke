"""Database fixtures and row builders for QA gate tests."""

from __future__ import annotations

import json

import pytest

from runtime.api.domain.qa_gates_reviewed_impl_test_support import (
    QA_SCHEMA,
    add_artifact,
    add_requirement,
    add_run,
)
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from runtime.api.api_workflow_test_helpers import (
    install_workflow_registry_and_pin_items,
)
from yoke_core.domain import db_backend
from yoke_core.domain.item_worktree_schema import ITEM_WORKTREES_TABLE_SQL
from yoke_core.domain.schema_init_apply import execute_schema_script

__all__ = (
    "add_artifact",
    "add_requirement",
    "add_run",
    "add_simulation",
    "apply_items_only",
    "qa_db",
)


def apply_qa_schema() -> None:
    conn = db_backend.connect()
    try:
        execute_schema_script(conn, QA_SCHEMA + ITEM_WORKTREES_TABLE_SQL)
        conn.execute(
            "INSERT INTO projects (id, slug, name, public_item_prefix) VALUES (1, 'yoke', 'Yoke', 'YOK')"
        )
        conn.execute(
            "INSERT INTO items (id, title, project_sequence) VALUES (42, 'Test item', 42)"
        )
        install_workflow_registry_and_pin_items(conn)
    finally:
        conn.close()


def apply_items_only() -> None:
    conn = db_backend.connect()
    try:
        conn.execute(
            "CREATE TABLE items (id INTEGER PRIMARY KEY, title TEXT, project_id INTEGER DEFAULT 1, project_sequence INTEGER)"
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def qa_db(tmp_path):
    with init_test_db(tmp_path, apply_schema=apply_qa_schema) as db_path:
        yield db_path


def add_simulation(
    db_path,
    epic_id,
    phase="integration",
    verdict="pass",
    body="",
):
    conn = connect_test_db(db_path)
    success_policy = json.dumps({"phase": phase})
    raw_result = json.dumps({"phase": phase, "body": body})
    cur = conn.execute(
        "INSERT INTO qa_requirements (item_id, qa_kind, qa_phase, success_policy, created_at) VALUES (%s, 'simulation', 'verification', %s, %s) RETURNING id",
        (epic_id, success_policy, "2026-04-20T00:00:00Z"),
    )
    req_id = int(cur.fetchone()[0])
    conn.execute(
        "INSERT INTO qa_runs (qa_requirement_id, executor_type, qa_kind, verdict, raw_result, created_at) VALUES (%s, 'simulation_engine', 'simulation', %s, %s, %s)",
        (req_id, verdict, raw_result, "2026-04-20T00:00:00Z"),
    )
    conn.commit()
    conn.close()
