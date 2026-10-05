"""Fresh-env schema chain creates the execution-instruction tables."""

from __future__ import annotations

from pathlib import Path

from yoke_core.domain.schema_common import _get_columns, _table_exists
from yoke_core.domain.workflow_execution_instructions_schema import (
    INSTRUCTION_PROJECTS_TABLE,
    INSTRUCTION_WORKFLOWS_TABLE,
    WORKFLOW_EXECUTION_INSTRUCTIONS_TABLE,
)
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


def test_fresh_init_creates_execution_instruction_tables(tmp_path: Path) -> None:
    with init_test_db(tmp_path) as db_path:
        conn = connect_test_db(db_path)
        try:
            assert _table_exists(conn, WORKFLOW_EXECUTION_INSTRUCTIONS_TABLE)
            assert _table_exists(conn, INSTRUCTION_WORKFLOWS_TABLE)
            assert _table_exists(conn, INSTRUCTION_PROJECTS_TABLE)
            cols = set(_get_columns(conn, WORKFLOW_EXECUTION_INSTRUCTIONS_TABLE))
            assert {
                "id",
                "content",
                "applies_to_all_workflows",
                "applies_to_all_projects",
                "updated_by_actor_id",
                "created_at",
                "updated_at",
            } <= cols
        finally:
            conn.close()


def test_init_replay_is_idempotent_for_execution_instructions(
    tmp_path: Path,
) -> None:
    from yoke_core.domain import schema_init

    with init_test_db(tmp_path) as db_path:
        schema_init.cmd_init()  # replay on an already-initialized DB
        conn = connect_test_db(db_path)
        try:
            assert _table_exists(conn, WORKFLOW_EXECUTION_INSTRUCTIONS_TABLE)
        finally:
            conn.close()


def test_delivery_columns_preserve_existing_rows_on_additive_convergence():
    import sqlite3
    from yoke_core.domain.workflow_execution_instructions_schema import (
        ensure_workflow_execution_instructions_schema,
    )

    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE workflows (id TEXT PRIMARY KEY);
        CREATE TABLE projects (id INTEGER PRIMARY KEY);
        CREATE TABLE workflow_execution_instructions (
            id INTEGER PRIMARY KEY, content TEXT NOT NULL,
            applies_to_all_workflows INTEGER NOT NULL DEFAULT 0,
            applies_to_all_projects INTEGER NOT NULL DEFAULT 0,
            updated_by_actor_id INTEGER, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        INSERT INTO workflow_execution_instructions (id, content, created_at, updated_at)
            VALUES (1, 'Existing rule', 'now', 'now');
    """)
    ensure_workflow_execution_instructions_schema(conn)
    ensure_workflow_execution_instructions_schema(conn)
    assert conn.execute(
        "SELECT before_creation, on_every_read, when_entering_stage, stage_buckets FROM workflow_execution_instructions"
    ).fetchone() == (1, 1, 0, "[]")
