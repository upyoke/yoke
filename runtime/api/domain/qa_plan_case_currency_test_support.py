# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item

from runtime.api.fixtures.pg_testdb import test_database

from yoke_core.domain.qa_plan_attachments import (
    materialize_for_item,
    set_project_default,
)

from yoke_core.domain.qa_plan_case_currency import (
    CURRENT,
    ORPHANED,
    STALE,
    STALE_PLAN_CASE_CODE,
    annotate_plan_currency,
    plan_case_divergence,
    plan_drift_report,
)

from yoke_core.domain.qa_plan_execution_state import begin_plan_execution

from yoke_core.domain.qa_plan_management import (
    QaPlanError,
    create_plan,
    replace_plan_cases,
)

from yoke_core.domain.qa_plan_execution_roster_correction import (
    ROSTER_CASE_REACHED_CODE,
)

from yoke_core.domain.qa_plan_rematerialize import rematerialize_for_item

TRANSITION = "implemented"

ORIGINAL_INSTRUCTIONS = "Run the target command."

CORRECTED_INSTRUCTIONS = "Run the target command, then settle before asserting."


def _case(**overrides):
    case = {
        "case_key": "command",
        "position": 1,
        "method_id": "command",
        "instructions": ORIGINAL_INSTRUCTIONS,
        "expected_outcome": "The command passes.",
        "method_config": {"command": "true"},
    }
    case.update(overrides)
    return case


def _materialized(conn, *, item_id: int) -> tuple[int, int]:
    """One item requirement materialized from a one-case plan."""
    insert_item(conn, id=item_id, title="Run targeted QA", workflow_id="issue")
    plan = create_plan(
        conn,
        project="yoke",
        slug=f"currency-plan-{item_id}",
        name="Currency plan",
    )
    plan_id = int(plan["id"])
    replace_plan_cases(conn, plan_id=plan_id, cases=[_case()])
    set_project_default(
        conn, plan_id=plan_id, workflow_id="issue", transition_id=TRANSITION
    )
    result = materialize_for_item(conn, item_id=item_id, transition_id=TRANSITION)
    return plan_id, int(result["created_requirement_ids"][0])


def _correct_the_case(conn, plan_id: int) -> dict:
    return replace_plan_cases(
        conn,
        plan_id=plan_id,
        cases=[_case(instructions=CORRECTED_INSTRUCTIONS)],
    )
