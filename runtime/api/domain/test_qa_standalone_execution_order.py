"""Standalone readers share durable allocation order independent of snapshots."""

import pytest

from yoke_contracts.timestamps import parse_instant

from runtime.api.fixtures.pg_testdb import test_database
from runtime.api.domain.test_qa_plan_standalone_execution import _begin, _plan
from yoke_core.domain import qa_standalone_execution as standalone
from yoke_core.domain.qa_plan_execution_continuation import latest_plan_execution
from yoke_core.domain.qa_plan_execution_schema import (
    assert_qa_plan_execution_schema_invariants,
    converge_qa_plan_execution_schema,
)
from yoke_core.domain.qa_plan_execution_state import finish_plan_execution
from yoke_core.domain.qa_plan_execution_store import (
    roster_digest,
    select_plan_execution,
)


def _empty_execution(conn, plan_id, execution_id, state, created_at):
    conn.execute(
        "INSERT INTO qa_plan_executions "
        "(id, standalone_plan_id, session_id, roster_digest, roster_json, "
        "state, created_at, heartbeat_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            execution_id,
            plan_id,
            "manual-owner",
            roster_digest([]),
            "[]",
            state,
            created_at,
            created_at,
        ),
    )
    return select_plan_execution(conn, execution_id, lock=False)


@pytest.mark.parametrize("new_state", ["active", "aborted"])
@pytest.mark.parametrize("older_has_requirements", [True, False])
def test_same_second_new_execution_without_requirements_is_latest(
    monkeypatch, new_state, older_has_requirements
):
    identifiers = iter(("f" * 32, "1" * 32))
    monkeypatch.setattr(standalone, "uuid4", lambda: next(identifiers))
    monkeypatch.setattr(
        standalone, "utc_now", lambda: parse_instant("2026-09-30T12:00:00Z")
    )
    with test_database() as conn:
        plan = _plan(conn)
        old = (
            _begin(conn)
            if older_has_requirements
            else _empty_execution(
                conn, plan["id"], "f" * 32, "active", standalone.utc_now()
            )
        )
        finish_plan_execution(conn, old, state="aborted", reason="restart")
        # A new execution is durable before its requirement roster is populated.
        _empty_execution(conn, plan["id"], "1" * 32, new_state, old["created_at"])
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM qa_requirements WHERE standalone_execution_id=%s",
                ("1" * 32,),
            ).fetchone()[0]
            == 0
        )
        for latest in (
            standalone._latest(conn, plan["id"]),
            latest_plan_execution(conn, standalone_plan_id=plan["id"]),
        ):
            assert latest["id"] == "1" * 32
            assert latest["execution_order"] > old["execution_order"]


def test_additive_boot_assigns_order_and_converges_idempotently():
    with test_database() as conn:
        plan = _plan(conn)
        old = _begin(conn)
        finish_plan_execution(conn, old, state="aborted", reason="restart")
        # Recreate the pre-column shape in this disposable fixture database.
        conn.execute("ALTER TABLE qa_plan_executions DROP COLUMN execution_order")
        converge_qa_plan_execution_schema(conn)
        first_order = standalone._latest(conn, plan["id"])["execution_order"]
        converge_qa_plan_execution_schema(conn)
        assert_qa_plan_execution_schema_invariants(conn)
        assert standalone._latest(conn, plan["id"])["execution_order"] == first_order
        new = _begin(conn)
        assert new["execution_order"] > first_order


def test_live_owner_precedes_later_terminal_history():
    with test_database() as conn:
        plan = _plan(conn)
        live = _begin(conn)
        _empty_execution(
            conn, plan["id"], "later-terminal", "aborted", live["created_at"]
        )
        assert standalone._latest(conn, plan["id"])["id"] == live["id"]
        assert (
            latest_plan_execution(conn, standalone_plan_id=plan["id"])["id"]
            == live["id"]
        )


def test_same_second_abort_then_restart_resumes_the_new_live_owner(monkeypatch):
    from yoke_core.domain import qa_standalone_execution as standalone
    from yoke_core.domain.qa_plan_execution_continuation import latest_plan_execution

    identifiers = iter(("f" * 32, "1" * 32, "2" * 32))
    monkeypatch.setattr(standalone, "uuid4", lambda: next(identifiers))
    monkeypatch.setattr(
        standalone, "utc_now", lambda: parse_instant("2026-09-30T12:00:00Z")
    )
    with test_database() as conn:
        _plan(conn)
        old = _begin(conn)
        finish_plan_execution(conn, old, state="aborted", reason="first")
        current = _begin(conn)
        resumed = _begin(conn)
        assert resumed["id"] == current["id"]
        finish_plan_execution(conn, current, state="aborted", reason="second")
        latest = latest_plan_execution(
            conn, standalone_plan_id=current["standalone_plan_id"]
        )
        assert latest["id"] == current["id"]
