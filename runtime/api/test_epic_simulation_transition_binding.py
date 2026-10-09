"""Workflow-transition binding coverage for epic simulations."""

from __future__ import annotations

import sys
from unittest.mock import patch

import pytest

from runtime.api.conftest import insert_item
from runtime.api.fixtures.file_test_db import (
    apply_fixture_schema_ddl,
    connect_test_db,
    init_test_db,
)
from yoke_core.domain import epic
from yoke_core.domain.project_identity import render_item_ref


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
        patch("yoke_core.domain.epic._qa_run_add_silent", return_value=5),
        patch("yoke_core.domain.epic_review_qa.verify_simulation_attempt"),
    ):
        epic.simulation_upsert(
            db,
            "42",
            "integration",
            f"SIMULATION: CLEAN\nEPIC: {render_item_ref(db, 42)}",
        )

    assert (
        add_req.call_args.kwargs["workflow_transition_id"] == "reviewed-implementation"
    )

    assert add_req.call_args.kwargs["target_env"] is None

    assert (
        db.execute("SELECT status FROM items WHERE id = 42").fetchone()[0]
        == "reviewed-implementation"
    )


def test_simulation_requirement_is_not_an_environment_observation(tmp_path) -> None:
    with init_test_db(tmp_path, apply_schema=apply_fixture_schema_ddl) as db_path:
        conn = connect_test_db(db_path)
        try:
            insert_item(
                conn, id=42, title="Test epic", workflow_id="epic", status="idea"
            )
            conn.commit()

            def bind_target(_conn, *, item_id, row):
                assert item_id == 42
                assert row["target_env"] is None
                return ""

            with (
                patch(
                    "yoke_core.domain.qa_requirements.connect",
                    side_effect=lambda **_: connect_test_db(db_path),
                ),
                patch(
                    "yoke_core.domain.qa_environment_execution_target.bind_item_named_target",
                    side_effect=bind_target,
                ) as bind,
                patch("yoke_core.domain.epic._qa_run_add_silent", return_value=5),
                patch("yoke_core.domain.epic_review_qa.verify_simulation_attempt"),
            ):
                receipt = epic.simulation_upsert(
                    conn,
                    "42",
                    "plan",
                    f"SIMULATION: CLEAN\nEPIC: {render_item_ref(conn, 42)}",
                )
            assert bind.call_count == 1
            row = conn.execute(
                "SELECT target_env FROM qa_requirements WHERE id=%s",
                (receipt.requirement_id,),
            ).fetchone()
            assert row[0] is None
        finally:
            conn.close()


def test_simulation_requirement_refusal_keeps_the_diagnostic(db) -> None:
    insert_item(db, id=42, title="Test epic", workflow_id="epic", status="idea")

    def refused(**_):
        print("qa_target_invalid: name a reviewable environment", file=sys.stderr)
        raise SystemExit(2)

    with patch("yoke_core.domain.epic._qa_requirement_add_silent", side_effect=refused):
        with pytest.raises(
            RuntimeError,
            match="simulation_requirement_create_failed:.*qa_target_invalid",
        ) as error:
            epic.simulation_upsert(
                db, "42", "plan", f"SIMULATION: CLEAN\nEPIC: {render_item_ref(db, 42)}"
            )
    assert "simulation-get before retrying" in str(error.value)
