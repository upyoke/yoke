# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

import pytest

from runtime.api.fixtures.dispatch_actor import register_session_actor

from runtime.api.fixtures.pg_testdb import test_database

from runtime.api.fixtures.qa_captured_plan_review_fixture import captured_plan_review

from runtime.api.fixtures.session_holdings import insert_item_claim

from yoke_core.domain.db_helpers import query_one

from yoke_core.domain.qa_plan_execution_adoption import adopt_execution

from yoke_core.domain.qa_plan_execution_authority import require_plan_execution_owner

from yoke_core.domain.qa_plan_execution_store import lock_plan_execution

from yoke_core.domain.qa_plan_review import begin_plan_review

from yoke_core.domain.qa_plan_review_submission import submit_plan_review

from yoke_core.domain.schema_init_tables import create_governed_tables


def _setup(conn, *, ended=True, claim=True, stamp="terminated_at"):
    execution, requirement, capture = captured_plan_review(conn, 4901)
    create_governed_tables(conn)
    register_session_actor(conn, execution["session_id"])
    actor = register_session_actor(conn, "successor-session")
    if ended:
        assert stamp in {"terminated_at", "ended_at"}
        conn.execute(
            f"UPDATE harness_sessions SET {stamp}=CURRENT_TIMESTAMP WHERE session_id=%s",
            (execution["session_id"],),
        )
    conn.commit()
    if claim:
        insert_item_claim(conn, "successor-session", 4901)
        conn.commit()
    return execution, requirement, capture, str(actor)


def _adopt(conn, execution, actor, **kwargs):
    return adopt_execution(
        conn,
        execution["id"],
        item_id=4901,
        actor_id=actor,
        session_id="successor-session",
        reason="Continue captured QA after restaffing",
        **kwargs,
    )
