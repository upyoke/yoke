# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

import pytest

from runtime.api.fixtures.pg_testdb import test_database

from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases

from yoke_core.domain.qa_requirement_snapshot_validation import (
    assert_requirement_execution_snapshot_invariants,
)

from yoke_core.domain.qa_plan_execution_state import (
    advance_plan_execution,
    finish_plan_execution,
    lock_plan_execution,
)

from yoke_core.domain.qa_plan_execution_store import QaPlanExecutionStateError

from yoke_core.domain.qa_case_execution_context import get_case_execution_context

from yoke_core.domain.qa_standalone_execution import begin_standalone_execution

from yoke_core.domain.qa_standalone_schema import assert_standalone_subjects

from yoke_core.domain.qa_plan_detail import get_plan

from yoke_core.domain.qa_artifact_owner import requirement_storage_owner

from yoke_core.domain.qa_artifacts import case_artifact_subject

SHA = "a" * 40


def _plan(conn):
    plan = create_plan(conn, project="yoke", slug="manual-proof", name="Manual proof")
    replace_plan_cases(
        conn,
        plan_id=plan["id"],
        cases=[
            {
                "case_key": key,
                "position": position,
                "method_id": "command",
                "instructions": "Run the command",
                "expected_outcome": "It passes",
                "method_config": {"command": "true"},
            }
            for key, position in (("later", 2), ("first", 1))
        ],
    )
    conn.commit()
    return plan


def _begin(conn, **kwargs):
    return begin_standalone_execution(
        conn,
        plan="manual-proof",
        project="yoke",
        actor_id="7",
        session_id="manual-owner",
        source_revision=SHA,
        checkout_path="/tmp/manual-proof",
        **kwargs,
    )
