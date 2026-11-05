# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import pytest

from psycopg.pq import TransactionStatus

from runtime.api.fixtures.backlog_inserts import insert_item

from runtime.api.fixtures.pg_testdb import test_database

from yoke_core.domain.qa_plan_attachments import (
    materialize_for_item,
    set_project_default,
)

from yoke_core.domain.qa_plan_execution_state import (
    QaPlanExecutionStateError,
    advance_plan_execution,
    begin_plan_execution,
    finish_plan_execution,
    lock_plan_execution,
    plan_execution_view,
)

from yoke_core.domain.qa_plan_management import (
    create_plan,
    replace_plan_cases,
)


def _materialize_two_cases(conn, *, item_id: int, commit: bool = True) -> list[int]:
    insert_item(
        conn,
        id=item_id,
        title="Run durable ordered QA",
        workflow_id="issue",
    )
    plan = create_plan(
        conn,
        project="yoke",
        slug=f"durable-plan-{item_id}",
        name="Durable plan",
    )
    replace_plan_cases(
        conn,
        plan_id=int(plan["id"]),
        cases=[
            {
                "case_key": "first-command",
                "position": 1,
                "method_id": "command",
                "instructions": "Run the first command.",
                "expected_outcome": "The first command passes.",
                "method_config": {"command": "true"},
            },
            {
                "case_key": "second-command",
                "position": 2,
                "method_id": "command",
                "instructions": "Run the second command.",
                "expected_outcome": "The second command passes.",
                "method_config": {"command": "true"},
            },
        ],
    )
    set_project_default(
        conn,
        plan_id=int(plan["id"]),
        workflow_id="issue",
        transition_id="implemented",
    )
    materialized = materialize_for_item(
        conn,
        item_id=item_id,
        transition_id="implemented",
        commit=commit,
    )
    return [int(value) for value in materialized["created_requirement_ids"]]


def _result(requirement_id: int) -> dict:
    return {
        "requirement_id": requirement_id,
        "runner_id": "worktree_run",
        "verdict": "pass",
        "case_outcome": "passed",
    }
