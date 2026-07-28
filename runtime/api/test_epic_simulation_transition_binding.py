"""Workflow-transition binding coverage for epic simulations."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from runtime.api.conftest import insert_item
from runtime.api.fixtures.file_test_db import (
    apply_fixture_schema_ddl,
    connect_test_db,
    init_test_db,
)
from yoke_core.domain import epic


@pytest.fixture
def db(tmp_path):
    with init_test_db(tmp_path, apply_schema=apply_fixture_schema_ddl) as db_path:
        conn = connect_test_db(db_path)
        try:
            yield conn
        finally:
            conn.close()


def test_integration_simulation_binds_to_the_qa_gate(db) -> None:
    insert_item(
        db,
        id=42,
        title="Test epic",
        workflow_id="epic",
        status="reviewed-implementation",
    )
    with (
        patch(
            "yoke_core.domain.epic._qa_requirement_add_silent",
            return_value=24,
        ) as add_req,
        patch("yoke_core.domain.epic._qa_run_add_silent"),
    ):
        epic.simulation_upsert(db, "42", "integration", "SIMULATION: CLEAN")

    assert (
        add_req.call_args.kwargs["workflow_transition_id"]
        == "reviewed-implementation"
    )
