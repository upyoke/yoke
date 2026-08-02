"""Registered command to executable QA-plan registration tests."""

from __future__ import annotations

from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain.qa_command_plan_registration import (
    ensure_registered_command_plan,
)


def test_current_model_seed_converges_without_legacy_settings() -> None:
    with test_database() as conn:
        first = ensure_registered_command_plan(
            conn,
            project_id=1,
            project="yoke",
            scope="full",
            command="python3 -m pytest",
        )
        second = ensure_registered_command_plan(
            conn,
            project_id=1,
            project="yoke",
            scope="full",
            command="python3 -m pytest",
        )
        legacy = conn.execute(
            "SELECT COUNT(*) FROM project_structure "
            "WHERE family='command_definitions'"
        ).fetchone()[0]
        defaults = conn.execute(
            "SELECT workflow_id, transition_id "
            "FROM qa_plan_project_defaults WHERE plan_id=%s",
            (int(first["plan_id"]),),
        ).fetchall()

    assert second["plan_id"] == first["plan_id"]
    assert legacy == 0
    assert {
        (row["workflow_id"], row["transition_id"]) for row in defaults
    } == {
        ("blitz", "done"),
        ("dash", "done"),
        ("epic", "reviewed-implementation"),
        ("issue", "reviewed-implementation"),
    }
