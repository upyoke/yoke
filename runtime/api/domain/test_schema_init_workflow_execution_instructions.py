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
            cols = set(
                _get_columns(conn, WORKFLOW_EXECUTION_INSTRUCTIONS_TABLE)
            )
            assert {
                "id", "title", "content", "applies_to_all_projects",
                "ordering", "status", "updated_by_actor_id",
                "created_at", "updated_at",
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
