"""A live QA execution whose requirements changed after its roster froze."""

from __future__ import annotations

import pytest

from runtime.api.domain.test_qa_plan_execution_authority import (
    _materialize_two_cases,
    _result,
)
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain.qa_plan_execution_roster_change import (
    ROSTER_CHANGED_REASON,
    require_cursor_case_current,
)
from yoke_core.domain.qa_plan_execution_state import (
    QaPlanExecutionStateError,
    advance_plan_execution,
    begin_plan_execution,
    select_plan_execution,
)

OWNER = {"actor_id": "7", "session_id": "roster-change-session"}


def _begin(conn, item_id: int) -> dict:
    return begin_plan_execution(
        conn, item_id=item_id, transition_id="implemented", **OWNER
    )


def _supersede(conn, requirement_id: int, *, by: int) -> None:
    conn.execute(
        "UPDATE qa_requirements SET superseded_by_requirement_id=%s,"
        "superseded_at=now(),supersession_rationale=%s,"
        "supersession_source='operator' WHERE id=%s",
        (by, "corrected case passed", requirement_id),
    )
    conn.commit()


def _stored(conn, execution_id: str) -> dict:
    row = select_plan_execution(conn, execution_id, lock=False)
    conn.rollback()
    return row


def test_unstarted_execution_restarts_on_the_current_roster() -> None:
    with test_database() as conn:
        first, second = _materialize_two_cases(conn, item_id=4321)
        stale = _begin(conn, 4321)
        _supersede(conn, second, by=first)

        fresh = _begin(conn, 4321)

        assert fresh["id"] != stale["id"]
        assert [case["requirement_id"] for case in fresh["roster"]] == [first]
        retired = _stored(conn, str(stale["id"]))
        assert retired["state"] == "aborted"
        assert retired["release_reason"] == ROSTER_CHANGED_REASON
        assert _stored(conn, str(fresh["id"]))["state"] == "active"


def test_partially_run_execution_refuses_with_the_abort_command() -> None:
    with test_database() as conn:
        first, second = _materialize_two_cases(conn, item_id=4322)
        execution = _begin(conn, 4322)
        advance_plan_execution(
            conn,
            execution,
            ordinal=0,
            requirement_id=first,
            result=_result(first),
        )
        _supersede(conn, second, by=first)

        with pytest.raises(QaPlanExecutionStateError) as refused:
            _begin(conn, 4322)

        message = str(refused.value)
        assert message.startswith("qa_roster_changed:")
        assert f"yoke qa plan abort --execution-id {execution['id']} --item " in message
        assert "--reason TEXT" in message
        assert _stored(conn, str(execution["id"]))["state"] == "active"


def test_checkin_refuses_a_superseded_cursor_case_before_it_runs() -> None:
    with test_database() as conn:
        first, second = _materialize_two_cases(conn, item_id=4323)
        execution = _begin(conn, 4323)
        require_cursor_case_current(conn, execution)

        _supersede(conn, first, by=second)

        with pytest.raises(QaPlanExecutionStateError) as refused:
            require_cursor_case_current(conn, execution)
        message = str(refused.value)
        assert message.startswith(f"qa_case_superseded: requirement {first} ")
        assert f"yoke qa plan abort --execution-id {execution['id']} " in message
