"""Database fixtures and row builders for QA gate tests."""

from __future__ import annotations

import json

import pytest

from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from runtime.api.api_workflow_test_helpers import (
    install_workflow_registry_and_pin_items,
)
from yoke_core.domain import db_backend
from yoke_core.domain.item_worktree_schema import ITEM_WORKTREES_TABLE_SQL
from yoke_core.domain.schema_init_apply import execute_schema_script

QA_SCHEMA = """
CREATE TABLE projects (id INTEGER PRIMARY KEY, slug TEXT UNIQUE, name TEXT, public_item_prefix TEXT DEFAULT 'YOK');
CREATE TABLE items (
    id INTEGER PRIMARY KEY,
    title TEXT,
    status TEXT DEFAULT 'implementing',
    project_id INTEGER DEFAULT 1, project_sequence INTEGER NOT NULL
);
CREATE TABLE epic_tasks (
    epic_id INTEGER,
    task_num INTEGER,
    status TEXT,
    item_worktree_id INTEGER,
    PRIMARY KEY (epic_id, task_num)
);
CREATE TABLE qa_requirements (
    id INTEGER PRIMARY KEY,
    item_id INTEGER,
    epic_id INTEGER,
    task_num INTEGER,
    deployment_run_id TEXT,
    qa_kind TEXT NOT NULL,
    qa_phase TEXT NOT NULL,
    blocking_mode TEXT NOT NULL DEFAULT 'blocking',
    requirement_source TEXT DEFAULT 'explicit',
    success_policy TEXT,
    method_id TEXT,
    waived_at TEXT,
    created_at TEXT
);
CREATE TABLE qa_runs (
    id INTEGER PRIMARY KEY,
    qa_requirement_id INTEGER,
    executor_type TEXT,
    qa_kind TEXT,
    verdict TEXT,
    raw_result TEXT,
    created_at TEXT
);
CREATE TABLE qa_artifacts (
    id INTEGER PRIMARY KEY,
    qa_run_id INTEGER,
    artifact_type TEXT,
    content_type TEXT,
    artifact_handle TEXT,
    metadata TEXT
);
-- No epic_simulations table: simulations use qa_requirements + qa_runs.
"""


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


def add_requirement(
    db_path,
    item_id=42,
    qa_kind="implementation_review",
    qa_phase="verification",
    blocking="blocking",
    method_id=None,
):
    conn = connect_test_db(db_path)
    cur = conn.execute(
        "INSERT INTO qa_requirements "
        "(item_id, qa_kind, qa_phase, blocking_mode, method_id, created_at) "
        "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
        (
            item_id,
            qa_kind,
            qa_phase,
            blocking,
            method_id,
            "2026-04-20T00:00:00Z",
        ),
    )
    req_id = int(cur.fetchone()[0])
    conn.commit()
    conn.close()
    return req_id


def add_run(
    db_path,
    req_id,
    verdict="pass",
    executor_type="agent",
    created_at=None,
    raw_result=None,
):
    conn = connect_test_db(db_path)
    ts = created_at or "2026-04-20T00:00:00Z"
    cur = conn.execute(
        "INSERT INTO qa_runs (qa_requirement_id, verdict, executor_type, raw_result, created_at) VALUES (%s, %s, %s, %s, %s) RETURNING id",
        (req_id, verdict, executor_type, raw_result, ts),
    )
    run_id = int(cur.fetchone()[0])
    conn.commit()
    conn.close()
    return run_id


def add_artifact(db_path, run_id, handle=None):
    """Insert an artifact, using a missing local screenshot by default."""
    from yoke_core.domain.qa_artifact_handle import (
        local_handle,
        serialize_handle,
    )

    if handle is None:
        handle = local_handle("test/screenshot.png")
    elif isinstance(handle, str):
        handle = local_handle(handle)
    conn = connect_test_db(db_path)
    conn.execute(
        "INSERT INTO qa_artifacts (qa_run_id, artifact_type, artifact_handle) VALUES (%s, 'screenshot', %s)",
        (run_id, serialize_handle(handle)),
    )
    conn.commit()
    conn.close()


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
