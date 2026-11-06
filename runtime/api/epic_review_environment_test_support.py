# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from contextlib import contextmanager

from unittest.mock import patch

import pytest

from runtime.api.conftest import insert_epic_task, insert_item

from runtime.api.domain.handlers._epic_task_review_state_test_helpers import (
    make_request,
)

from runtime.api.domain.qa_planless_case_execution_target_test_support import (
    _environment,
)

from runtime.api.fixtures.file_test_db import (
    apply_test_schema,
    connect_test_db,
    init_test_db,
)

from yoke_core.domain.handlers import workflow_item_epic_task_review as handlers

from yoke_core.domain.qa_requirements import cmd_requirement_add


@pytest.fixture
def review_db(tmp_path):
    with init_test_db(tmp_path, apply_schema=apply_test_schema) as db_path:
        conn = connect_test_db(db_path)
        try:
            insert_item(
                conn,
                id=42,
                title="Source review",
                workflow_id="epic",
                status="implementing",
            )
            insert_epic_task(
                conn, epic_id=42, task_num=1, title="Committed task", status="planning"
            )
            _environment(conn, name="local")

            @contextmanager
            def opened():
                yield conn

            with (
                patch.object(handlers, "_open_connection", opened),
                patch(
                    "yoke_core.domain.qa_requirements.connect",
                    side_effect=lambda **_: connect_test_db(db_path),
                ),
            ):
                yield conn
        finally:
            conn.close()
