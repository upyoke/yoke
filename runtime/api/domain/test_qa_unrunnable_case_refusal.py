"""A QA case that cannot run must say so instead of exiting quietly.

Two boundaries mint or dispatch an executable case: materialization turns
a plan case into a requirement, and the CI runner dispatches one. Both
refuse a Command case whose contract carries no runnable command, so an
unrunnable case is named where it is created and where it would run
rather than producing an empty verdict nobody can attribute.
"""

from __future__ import annotations

import json
from unittest import mock

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain import qa_case_ci_run
from yoke_core.domain.qa_case_execution import QaCaseExecutionError
from yoke_core.domain.qa_plan_attachments import (
    materialize_for_item,
    set_project_default,
)
from yoke_core.domain.qa_plan_management import QaPlanError, create_plan

ITEM_ID = 44
TRANSITION_ID = "implemented"


def _ci_case(config: dict) -> dict:
    return {
        "requirement_id": 41,
        "item_id": ITEM_ID,
        "plan_id": 5,
        "case_key": "registered",
        "method_id": "command-ci",
        "runner_id": "ci_run",
        "method_config": config,
        "project_id": 1,
        "project": "yoke",
        "lane_branch": None,
    }


def _plan_with_case_config(conn, config: dict) -> int:
    """Author a plan whose stored case bypassed contract validation."""
    insert_item(conn, id=ITEM_ID, title="Run verification", workflow_id="issue")
    plan = create_plan(
        conn,
        project="yoke",
        slug="unvalidated-command",
        name="Unvalidated command",
    )
    conn.execute(
        "INSERT INTO qa_plan_cases("
        "plan_id, case_key, position, method_id, instructions, "
        "expected_outcome, method_config, created_at, updated_at"
        ") VALUES (%s, 'registered', 1, 'command', %s, %s, %s, %s, %s)",
        (
            int(plan["id"]),
            "Run the registered verification command.",
            "The command exits successfully.",
            json.dumps(config),
            "2026-08-15T00:00:00Z",
            "2026-08-15T00:00:00Z",
        ),
    )
    set_project_default(
        conn,
        plan_id=int(plan["id"]),
        workflow_id="issue",
        transition_id=TRANSITION_ID,
    )
    return int(plan["id"])


def test_ci_case_refuses_an_empty_command_before_touching_the_lane() -> None:
    """The refusal lands before the checkout, the push, and the dispatch."""
    case = _ci_case(
        {"command": "   ", "ci_workflow": "ci.yml", "registered_scope": "full"},
    )

    with mock.patch.object(qa_case_ci_run, "_resolve_checkout") as resolve:
        with pytest.raises(QaCaseExecutionError) as failure:
            qa_case_ci_run.execute_ci_case(case)

    assert "method_config.command" in str(failure.value)
    resolve.assert_not_called()


def test_ci_case_names_the_missing_workflow_with_its_remediation() -> None:
    """A runnable command with no workflow keeps the declaring remedy."""
    case = _ci_case({"command": "true", "registered_scope": "full"})

    with mock.patch.object(qa_case_ci_run, "_resolve_checkout") as resolve:
        with pytest.raises(QaCaseExecutionError) as failure:
            qa_case_ci_run.execute_ci_case(case)

    assert "ci_workflow_file" in str(failure.value)
    resolve.assert_not_called()


def test_materialization_refuses_a_command_case_with_an_empty_command() -> None:
    """No requirement is minted from a case that could never run."""
    with test_database() as conn:
        _plan_with_case_config(conn, {"command": "", "registered_scope": "full"})

        with pytest.raises(QaPlanError) as failure:
            materialize_for_item(
                conn,
                item_id=ITEM_ID,
                transition_id=TRANSITION_ID,
            )

        conn.rollback()
        assert "registered" in str(failure.value)
        assert "method_config.command" in str(failure.value)
        remaining = conn.execute(
            "SELECT COUNT(*) AS total FROM qa_requirements WHERE item_id=%s",
            (ITEM_ID,),
        ).fetchone()
        assert int(remaining["total"]) == 0


def test_materialization_accepts_a_runnable_command_case() -> None:
    """The refusal is specific to an unrunnable contract, not to the path."""
    with test_database() as conn:
        _plan_with_case_config(
            conn,
            {"command": "true", "registered_scope": "full"},
        )

        materialized = materialize_for_item(
            conn,
            item_id=ITEM_ID,
            transition_id=TRANSITION_ID,
        )

        assert len(materialized["created_requirement_ids"]) == 1
