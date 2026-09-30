"""Manual project plans own fresh snapshots without item or delivery gates."""

import pytest

from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases
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


def test_fresh_manual_runs_keep_order_and_never_acquire_gate_subjects():
    with test_database() as conn:
        _plan(conn)
        assert_standalone_subjects(conn)
        execution = _begin(conn)
        assert [case["case_key"] for case in execution["roster"]] == ["first", "later"]
        for case in execution["roster"]:
            assert case["item_id"] is None and case["deployment_run_id"] is None
            assert case["workflow_transition_id"] is None
            assert case["standalone_execution_id"] == execution["id"]
            assert (
                get_case_execution_context(conn, requirement_id=case["requirement_id"])[
                    "standalone_source_revision"
                ]
                == SHA
            )
        finish_plan_execution(conn, execution, state="aborted", reason="manual-abort")
        fresh = _begin(conn)
        owner = requirement_storage_owner(conn, fresh["roster"][0]["requirement_id"])
        assert owner["project"] == "yoke"
        assert case_artifact_subject(owner) == f"standalone-{fresh['id']}"
        proof = get_plan(conn, plan_id=fresh["standalone_plan_id"])["cases"][0][
            "proofs"
        ][0]
        assert proof["standalone_execution_id"] == fresh["id"]
        assert fresh["id"] != execution["id"]
        assert {case["requirement_id"] for case in fresh["roster"]}.isdisjoint(
            case["requirement_id"] for case in execution["roster"]
        )
        assert (
            conn.execute("SELECT COUNT(*) FROM qa_plan_item_attachments").fetchone()[0]
            == 0
        )


def test_manual_resume_keeps_snapshot_cursor_and_source_binding():
    with test_database() as conn:
        _plan(conn)
        execution = _begin(conn)
        case = execution["roster"][0]
        advance_plan_execution(
            conn,
            execution,
            ordinal=0,
            requirement_id=case["requirement_id"],
            result={
                "requirement_id": case["requirement_id"],
                "runner_id": "worktree_run",
                "verdict": "pass",
                "case_outcome": "passed",
            },
        )
        resumed = _begin(conn)
        assert resumed["id"] == execution["id"]
        assert resumed["cursor_ordinal"] == 1
        with pytest.raises(
            QaPlanExecutionStateError, match="standalone_source_changed"
        ):
            begin_standalone_execution(
                conn,
                plan="manual-proof",
                project="yoke",
                actor_id="7",
                session_id="manual-owner",
                source_revision="b" * 40,
            )
        conn.rollback()
        assert (
            lock_plan_execution(conn, execution["id"])["roster_digest"]
            == resumed["roster_digest"]
        )


def test_bad_source_refuses_before_materialization_commits():
    with test_database() as conn:
        _plan(conn)
        with pytest.raises(
            QaPlanExecutionStateError, match="standalone_commit_required"
        ):
            begin_standalone_execution(
                conn,
                plan="manual-proof",
                project="yoke",
                actor_id="7",
                session_id="manual-owner",
            )
        conn.rollback()
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM qa_requirements WHERE standalone_execution_id IS NOT NULL"
            ).fetchone()[0]
            == 0
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM qa_plan_executions WHERE standalone_plan_id IS NOT NULL"
            ).fetchone()[0]
            == 0
        )
