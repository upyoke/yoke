"""Durable cursor, ownership, and idempotency for ordered QA plans."""

from __future__ import annotations

from runtime.api.domain.qa_plan_execution_authority_test_support import (
    _materialize_two_cases as _materialize_two_cases,
    _result as _result,
)


import pytest
from psycopg.pq import TransactionStatus

from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain.qa_plan_execution_state import (
    QaPlanExecutionStateError,
    advance_plan_execution,
    begin_plan_execution,
    finish_plan_execution,
    lock_plan_execution,
    plan_execution_view,
)


def test_durable_cursor_resumes_without_replaying_completed_cases() -> None:
    with test_database() as conn:
        requirement_ids = _materialize_two_cases(conn, item_id=4401)
        execution = begin_plan_execution(
            conn,
            item_id=4401,
            transition_id="implemented",
            actor_id="7",
            session_id="ordered-session",
        )
        assert [case["requirement_id"] for case in execution["roster"]] == (
            requirement_ids
        )

        # Only host-free cases record ahead of the cursor; any other case
        # waits for its turn.
        execution["roster"][1]["runner_id"] = "host_control"
        with pytest.raises(QaPlanExecutionStateError, match="expects ordinal 0"):
            advance_plan_execution(
                conn,
                execution,
                ordinal=1,
                requirement_id=requirement_ids[1],
                result=_result(requirement_ids[1]),
            )
        conn.rollback()
        execution = lock_plan_execution(conn, str(execution["id"]))
        advance_plan_execution(
            conn,
            execution,
            ordinal=0,
            requirement_id=requirement_ids[0],
            result=_result(requirement_ids[0]),
        )
        resumed = begin_plan_execution(
            conn,
            item_id=4401,
            transition_id="implemented",
            actor_id="7",
            session_id="ordered-session",
        )
        assert conn.info.transaction_status is TransactionStatus.IDLE
        view = plan_execution_view(conn, resumed)
        assert view["cursor_ordinal"] == 1
        assert [entry["requirement_id"] for entry in view["results"]] == [
            requirement_ids[0]
        ]

        advance_plan_execution(
            conn,
            resumed,
            ordinal=0,
            requirement_id=requirement_ids[0],
            result=_result(requirement_ids[0]),
        )
        assert (
            int(
                conn.execute(
                    "SELECT COUNT(*) FROM qa_plan_execution_results "
                    "WHERE execution_id=%s",
                    (str(execution["id"]),),
                ).fetchone()[0]
            )
            == 1
        )

        advance_plan_execution(
            conn,
            resumed,
            ordinal=1,
            requirement_id=requirement_ids[1],
            result=_result(requirement_ids[1]),
        )
        finish_plan_execution(
            conn,
            resumed,
            state="completed",
            reason="test-complete",
        )
        completed = lock_plan_execution(conn, str(execution["id"]))
        assert completed["state"] == "completed"
        assert completed["cursor_ordinal"] == 2


def test_live_execution_is_actor_session_bound() -> None:
    with test_database() as conn:
        _materialize_two_cases(conn, item_id=4402)
        begin_plan_execution(
            conn,
            item_id=4402,
            transition_id="implemented",
            actor_id="7",
            session_id="owner-session",
        )
        with pytest.raises(
            QaPlanExecutionStateError,
            match="another actor or session",
        ):
            begin_plan_execution(
                conn,
                item_id=4402,
                transition_id="implemented",
                actor_id="8",
                session_id="other-session",
            )


def test_completion_refuses_an_incomplete_cursor() -> None:
    with test_database() as conn:
        _materialize_two_cases(conn, item_id=4403)
        execution = begin_plan_execution(
            conn,
            item_id=4403,
            transition_id="implemented",
            actor_id="7",
            session_id="ordered-session",
        )
        with pytest.raises(QaPlanExecutionStateError, match="every case"):
            finish_plan_execution(
                conn,
                execution,
                state="completed",
                reason="too-early",
            )


def test_terminal_finish_replay_is_idempotent_and_cannot_change_outcome() -> None:
    with test_database() as conn:
        requirement_ids = _materialize_two_cases(conn, item_id=4404)
        execution = begin_plan_execution(
            conn,
            item_id=4404,
            transition_id="implemented",
            actor_id="7",
            session_id="ordered-session",
        )
        for ordinal, requirement_id in enumerate(requirement_ids):
            advance_plan_execution(
                conn,
                execution,
                ordinal=ordinal,
                requirement_id=requirement_id,
                result=_result(requirement_id),
            )
        finish_plan_execution(
            conn,
            execution,
            state="completed",
            reason="first-completion",
        )
        completed_at = execution["completed_at"]
        release_reason = execution["release_reason"]

        finish_plan_execution(
            conn,
            execution,
            state="completed",
            reason="replayed-completion",
        )
        replayed = lock_plan_execution(conn, str(execution["id"]))
        assert replayed["completed_at"] == completed_at
        assert replayed["release_reason"] == release_reason

        with pytest.raises(QaPlanExecutionStateError, match="already terminal"):
            finish_plan_execution(
                conn,
                replayed,
                state="aborted",
                reason="late-abort",
            )
