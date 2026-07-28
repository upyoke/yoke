"""Concurrency, takeover, and backend portability for QA plan authority."""

from __future__ import annotations

import sqlite3
import threading
from typing import Any

import psycopg
import pytest

from runtime.api.domain.test_qa_plan_execution_authority import (
    _materialize_two_cases,
    _result,
)
from runtime.api.fixtures.pg_testdb import (
    connect_test_database,
    dsn_for_test_database,
    test_database,
)
from yoke_core.domain.coordination_leases import (
    acquire_lease,
    get_lease,
)
from yoke_core.domain.qa_plan_execution_schema import (
    converge_qa_plan_execution_schema,
)
from yoke_core.domain.qa_plan_execution_state import (
    QaPlanExecutionStateError,
    advance_plan_execution,
    begin_plan_execution,
    finish_plan_execution,
    plan_execution_view,
    set_plan_machine_lease,
)
from yoke_core.domain.qa_plan_execution_store import (
    select_plan_execution,
)


def _begin_race(
    *,
    item_id: int,
    owners: tuple[tuple[str, str], tuple[str, str]],
) -> tuple[list[dict[str, Any]], int]:
    with test_database() as setup:
        _materialize_two_cases(setup, item_id=item_id)
        barrier = threading.Barrier(2)
        connections = [connect_test_database(setup.info.dbname) for _index in range(2)]
        outcomes: list[dict[str, Any]] = []
        outcome_lock = threading.Lock()

        def begin(index: int) -> None:
            actor_id, session_id = owners[index]
            try:
                barrier.wait(timeout=10)
                execution = begin_plan_execution(
                    connections[index],
                    item_id=item_id,
                    transition_id="implemented",
                    actor_id=actor_id,
                    session_id=session_id,
                )
                outcome = {"execution": execution}
            except BaseException as exc:
                outcome = {"error": exc}
            with outcome_lock:
                outcomes.append(outcome)

        workers = [threading.Thread(target=begin, args=(index,)) for index in range(2)]
        try:
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(timeout=15)
            assert all(not worker.is_alive() for worker in workers)
            live_count = int(
                setup.execute(
                    "SELECT COUNT(*) FROM qa_plan_executions "
                    "WHERE item_id=%s AND transition_id='implemented' "
                    "AND state IN ('active','waiting')",
                    (item_id,),
                ).fetchone()[0]
            )
        finally:
            for connection in connections:
                connection.close()
        return outcomes, live_count


def test_concurrent_begin_from_same_owner_converges_on_one_execution() -> None:
    outcomes, live_count = _begin_race(
        item_id=4410,
        owners=(("7", "same-session"), ("7", "same-session")),
    )

    assert live_count == 1, outcomes
    assert all("execution" in outcome for outcome in outcomes)
    assert len({outcome["execution"]["id"] for outcome in outcomes}) == 1


def test_concurrent_begin_from_different_owner_returns_domain_refusal() -> None:
    outcomes, live_count = _begin_race(
        item_id=4411,
        owners=(("7", "first-session"), ("8", "second-session")),
    )

    successes = [outcome["execution"] for outcome in outcomes if "execution" in outcome]
    failures = [outcome["error"] for outcome in outcomes if "error" in outcome]
    assert live_count == 1, outcomes
    assert len(successes) == 1
    assert len(failures) == 1
    assert isinstance(failures[0], QaPlanExecutionStateError)
    assert not isinstance(failures[0], psycopg.IntegrityError)
    assert "another actor or session" in str(failures[0])


def test_stale_owner_is_aborted_and_held_machine_lease_is_released() -> None:
    from yoke_core.domain.schema_init_tables import create_governed_tables

    with test_database() as conn:
        create_governed_tables(conn)
        _materialize_two_cases(conn, item_id=4412)
        stale = begin_plan_execution(
            conn,
            item_id=4412,
            transition_id="implemented",
            actor_id="7",
            session_id="stale-session",
        )
        lease = acquire_lease(
            conn,
            1,
            "TEST_MAC:ordered-plan-authority",
            "stale-session",
            actor_id="7",
        )
        set_plan_machine_lease(conn, stale, lease_id=lease.id)
        conn.execute(
            "UPDATE qa_plan_executions SET heartbeat_at='2000-01-01T00:00:00Z' "
            "WHERE id=%s",
            (str(stale["id"]),),
        )
        conn.commit()

        replacement = begin_plan_execution(
            conn,
            item_id=4412,
            transition_id="implemented",
            actor_id="8",
            session_id="replacement-session",
        )
        released = get_lease(conn, lease.id)
        prior = select_plan_execution(conn, str(stale["id"]), lock=False)

        assert replacement["id"] != stale["id"]
        assert prior["state"] == "aborted"
        assert prior["release_reason"] == "stale-heartbeat"
        assert prior["machine_lease_id"] is None
        assert released.is_active is False
        assert released.release_reason == "qa-plan-execution-stale"


@pytest.mark.parametrize("terminal_state", ["aborted", "error"])
def test_terminal_replay_preserves_outcome_and_refuses_other_states(
    terminal_state: str,
) -> None:
    with test_database() as conn:
        _materialize_two_cases(
            conn, item_id=4413 if terminal_state == "aborted" else 4414
        )
        execution = begin_plan_execution(
            conn,
            item_id=4413 if terminal_state == "aborted" else 4414,
            transition_id="implemented",
            actor_id="7",
            session_id=f"{terminal_state}-session",
        )
        finish_plan_execution(
            conn,
            execution,
            state=terminal_state,
            reason=f"first-{terminal_state}",
        )
        completed_at = execution["completed_at"]
        release_reason = execution["release_reason"]

        finish_plan_execution(
            conn,
            execution,
            state=terminal_state,
            reason="replayed-terminal",
        )
        assert execution["completed_at"] == completed_at
        assert execution["release_reason"] == release_reason

        for incompatible in {"completed", "aborted", "error", "waiting"} - {
            terminal_state
        }:
            with pytest.raises(QaPlanExecutionStateError, match="already terminal"):
                finish_plan_execution(
                    conn,
                    execution,
                    state=incompatible,
                    reason=f"late-{incompatible}",
                )


def test_default_postgres_tuple_rows_advance_and_render_execution_results() -> None:
    with test_database() as conn:
        requirement_ids = _materialize_two_cases(conn, item_id=4415)
        execution = begin_plan_execution(
            conn,
            item_id=4415,
            transition_id="implemented",
            actor_id="7",
            session_id="tuple-session",
        )
        dsn = dsn_for_test_database(conn.info.dbname)

        with psycopg.connect(dsn) as tuple_conn:
            stored = select_plan_execution(
                tuple_conn,
                str(execution["id"]),
                lock=False,
            )
            advance_plan_execution(
                tuple_conn,
                stored,
                ordinal=0,
                requirement_id=requirement_ids[0],
                result=_result(requirement_ids[0]),
            )
            advance_plan_execution(
                tuple_conn,
                stored,
                ordinal=0,
                requirement_id=requirement_ids[0],
                result=_result(requirement_ids[0]),
            )
            view = plan_execution_view(tuple_conn, stored)

        assert view["cursor_ordinal"] == 1
        assert view["results"][0]["requirement_id"] == requirement_ids[0]
        assert view["results"][0]["result"] == _result(requirement_ids[0])


def test_default_sqlite_rows_advance_replay_and_finish_portably() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("CREATE TABLE qa_requirements (id INTEGER PRIMARY KEY)")
        converge_qa_plan_execution_schema(conn)
        conn.execute("INSERT INTO qa_requirements(id) VALUES (1)")
        conn.execute(
            "INSERT INTO qa_plan_executions("
            "id,item_id,transition_id,actor_id,session_id,roster_digest,"
            "roster_json,state,created_at,heartbeat_at"
            ") VALUES ('sqlite-execution',1,'implemented','7','sqlite-session',"
            "'digest','[{\"requirement_id\":1,\"ordinal\":0}]','active',"
            "'then','then')"
        )
        conn.commit()
        execution = select_plan_execution(conn, "sqlite-execution", lock=False)
        result = _result(1)

        advance_plan_execution(
            conn,
            execution,
            ordinal=0,
            requirement_id=1,
            result=result,
        )
        advance_plan_execution(
            conn,
            execution,
            ordinal=0,
            requirement_id=1,
            result=result,
        )
        view = plan_execution_view(conn, execution)
        finish_plan_execution(
            conn,
            execution,
            state="completed",
            reason="sqlite-complete",
        )
        finish_plan_execution(
            conn,
            execution,
            state="completed",
            reason="sqlite-replay",
        )

        assert view["cursor_ordinal"] == 1
        assert view["results"] == [
            {
                "ordinal": 0,
                "requirement_id": 1,
                "result": result,
                "completed_at": view["results"][0]["completed_at"],
            }
        ]
        with pytest.raises(QaPlanExecutionStateError, match="already terminal"):
            finish_plan_execution(
                conn,
                execution,
                state="aborted",
                reason="sqlite-late-abort",
            )
    finally:
        conn.close()
