"""Database lifecycle fixture for reviewed-implementation QA gate tests."""

import os
from unittest import mock

import pytest

from runtime.api.api_workflow_test_helpers import (
    install_workflow_registry_and_pin_items,
)
from runtime.api.domain.qa_gates_reviewed_impl_test_support import QA_SCHEMA
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from yoke_core.domain import db_backend
from yoke_core.domain.item_worktree_schema import ITEM_WORKTREES_TABLE_SQL
from yoke_core.domain.schema_init_apply import execute_schema_script


def _apply_qa_schema() -> None:
    conn = db_backend.connect()
    try:
        execute_schema_script(conn, QA_SCHEMA + ITEM_WORKTREES_TABLE_SQL)
        conn.execute(
            "INSERT INTO projects "
            "(id, slug, name, public_item_prefix) "
            "VALUES (1, 'yoke', 'Yoke', 'YOK')",
        )
        install_workflow_registry_and_pin_items(conn)
    finally:
        conn.close()


@pytest.fixture
def qa_db(tmp_path):
    with init_test_db(tmp_path, apply_schema=_apply_qa_schema) as db_path:
        with mock.patch.dict(os.environ, {"YOKE_DB": db_path}, clear=False):
            conn = connect_test_db(db_path)
            conn.execute(
                "INSERT INTO items (id, title, project_sequence) "
                "VALUES (42, 'Test item', 42)",
            )
            install_workflow_registry_and_pin_items(conn)
            conn.close()
            yield db_path


__all__ = ["qa_db"]
