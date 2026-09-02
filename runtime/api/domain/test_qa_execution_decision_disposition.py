"""Ending a QA plan execution releases the decisions it asked a human."""

from __future__ import annotations

import pytest

from runtime.api.domain.test_qa_plan_execution_authority import (
    _materialize_two_cases,
)
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain.decision_request_disposition import (
    dispose_ended_decision_requests,
)
from yoke_core.domain.decision_request_resolution import (
    withdraw_for_ended_subject,
)
from yoke_core.domain.qa_plan_execution_lifecycle import (
    reap_stale_plan_executions,
)
from yoke_core.domain.qa_plan_execution_state import (
    QaPlanExecutionStateError,
    advance_plan_execution,
    begin_plan_execution,
    finish_plan_execution,
    lock_plan_execution,
)
from yoke_core.domain.qa_review_requests import ensure_qa_review_request


def _undetermined_walk(conn, *, item_id: int, session_id: str) -> tuple[dict, int]:
    """Walk one case to an undetermined verdict and raise its review request."""
    requirement_ids = _materialize_two_cases(conn, item_id=item_id)
    requirement_id = requirement_ids[0]
    execution = begin_plan_execution(
        conn,
        item_id=item_id,
        transition_id="implemented",
        actor_id="7",
        session_id=session_id,
    )
    advance_plan_execution(
        conn,
        execution,
        ordinal=0,
        requirement_id=requirement_id,
        result={"requirement_id": requirement_id, "verdict": "undetermined"},
    )
    run_id = conn.execute(
        "INSERT INTO qa_runs "
        "(qa_requirement_id, performed_by, qa_kind, verdict, verdict_reason, "
        "started_at, completed_at, created_at) "
        "VALUES (%s, 'agent', 'plan_case', 'undetermined', "
        "'The walker never reached the surface.', "
        "'2026-07-28T18:42:00Z', '2026-07-28T18:42:00Z', "
        "'2026-07-28T18:42:00Z') RETURNING id",
        (requirement_id,),
    ).fetchone()[0]
    request, created = ensure_qa_review_request(
        conn,
        requirement_id=int(requirement_id),
        run_id=int(run_id),
    )
    assert created is True and request is not None
    return execution, int(request["id"])


def _status(conn, request_id: int) -> tuple[str, str]:
    row = conn.execute(
        "SELECT status, withdrawal_reason FROM decision_requests WHERE id=%s",
        (request_id,),
    ).fetchone()
    return str(row[0]), str(row[1] or "")


def test_aborting_an_execution_withdraws_the_review_it_raised() -> None:
    with test_database() as conn:
        execution, request_id = _undetermined_walk(
            conn, item_id=4801, session_id="walk-session"
        )
        assert _status(conn, request_id)[0] == "pending"

        finish_plan_execution(
            conn,
            execution,
            state="aborted",
            reason="Operator aborted the walk after the host wipe did not land",
        )

        status, reason = _status(conn, request_id)
        assert status == "withdrawn"
        assert "ended as aborted" in reason
        assert "host wipe did not land" in reason


def test_completing_an_execution_withdraws_the_review_it_raised() -> None:
    with test_database() as conn:
        execution, request_id = _undetermined_walk(
            conn, item_id=4802, session_id="complete-session"
        )
        requirement_ids = [case["requirement_id"] for case in execution["roster"]]
        advance_plan_execution(
            conn,
            execution,
            ordinal=1,
            requirement_id=requirement_ids[1],
            result={"requirement_id": requirement_ids[1], "verdict": "pass"},
        )

        finish_plan_execution(
            conn,
            execution,
            state="completed",
            reason="qa-plan-agent-review-complete",
        )

        status, reason = _status(conn, request_id)
        assert status == "withdrawn"
        assert "ended as completed" in reason


def test_a_review_survives_while_another_execution_still_walks_it() -> None:
    with test_database() as conn:
        first, request_id = _undetermined_walk(
            conn, item_id=4803, session_id="first-session"
        )
        requirement_id = first["roster"][0]["requirement_id"]
        conn.execute(
            "INSERT INTO qa_plan_executions"
            "(id,item_id,transition_id,actor_id,session_id,roster_digest,"
            "roster_json,cursor_ordinal,state,created_at,heartbeat_at) "
            "VALUES ('second-walk',%s,'implementing','7','second-session',"
            "'digest','[]',0,'active','2026-07-28T18:42:00Z',"
            "'2026-07-28T18:42:00Z')",
            (4803,),
        )
        conn.execute(
            "INSERT INTO qa_plan_execution_results"
            "(execution_id,ordinal,requirement_id,result_json,completed_at) "
            "VALUES ('second-walk',0,%s,'{}','2026-07-28T18:42:00Z')",
            (requirement_id,),
        )
        conn.commit()

        finish_plan_execution(
            conn, first, state="aborted", reason="first walk abandoned"
        )

        assert _status(conn, request_id)[0] == "pending"
        with pytest.raises(ValueError, match="still being walked"):
            withdraw_for_ended_subject(
                conn, request_id, reason="premature", session_id="sweep"
            )


def test_a_standing_ad_hoc_review_is_never_disposed_of_by_the_sweep() -> None:
    with test_database() as conn:
        requirement_ids = _materialize_two_cases(conn, item_id=4804)
        requirement_id = requirement_ids[0]
        run_id = conn.execute(
            "INSERT INTO qa_runs "
            "(qa_requirement_id, performed_by, qa_kind, verdict, verdict_reason, "
            "started_at, completed_at, created_at) "
            "VALUES (%s, 'agent', 'plan_case', 'undetermined', "
            "'No walk ran this case.', '2026-07-28T18:42:00Z', "
            "'2026-07-28T18:42:00Z', '2026-07-28T18:42:00Z') RETURNING id",
            (requirement_id,),
        ).fetchone()[0]
        request, _created = ensure_qa_review_request(
            conn, requirement_id=int(requirement_id), run_id=int(run_id)
        )
        assert request is not None

        result = dispose_ended_decision_requests(conn)

        assert _status(conn, int(request["id"]))[0] == "pending"
        assert result["withdrawn_count"] == 0
        assert result["retained_count"] >= 1


def test_a_non_progressing_execution_is_reaped_and_its_review_released() -> None:
    with test_database() as conn:
        execution, request_id = _undetermined_walk(
            conn, item_id=4805, session_id="stranded-session"
        )
        conn.execute(
            "UPDATE qa_plan_executions SET heartbeat_at='2000-01-01T00:00:00Z' "
            "WHERE id=%s",
            (str(execution["id"]),),
        )
        conn.commit()

        reaped = reap_stale_plan_executions(conn)

        assert [row["execution_id"] for row in reaped] == [str(execution["id"])]
        assert all(row["reaped"] for row in reaped)
        settled = lock_plan_execution(conn, str(execution["id"]))
        conn.commit()
        assert settled["state"] == "aborted"
        assert settled["release_reason"] == "stale-heartbeat"
        status, reason = _status(conn, request_id)
        assert status == "withdrawn"
        assert "stale-heartbeat" in reason


def test_the_sweep_converges_a_walk_that_already_ended() -> None:
    with test_database() as conn:
        execution, request_id = _undetermined_walk(
            conn, item_id=4806, session_id="ended-session"
        )
        # Terminate the row the way a hand settlement does: no disposition.
        conn.execute(
            "UPDATE qa_plan_executions SET state='aborted',"
            "completed_at='2026-09-02T13:00:00Z',"
            "release_reason='Operator settlement' WHERE id=%s",
            (str(execution["id"]),),
        )
        conn.commit()
        assert _status(conn, request_id)[0] == "pending"

        result = dispose_ended_decision_requests(conn)

        assert _status(conn, request_id)[0] == "withdrawn"
        assert [row["request_id"] for row in result["withdrawn"]] == [request_id]
        assert "no live plan execution left" in result["withdrawn"][0]["evidence"]


def test_a_vintage_execution_without_a_target_still_runs_nothing_but_aborts() -> None:
    with test_database() as conn:
        execution, _request_id = _undetermined_walk(
            conn, item_id=4807, session_id="vintage-session"
        )
        conn.execute(
            "UPDATE qa_plan_executions SET execution_target_json=NULL,"
            "execution_target_digest=NULL WHERE id=%s",
            (str(execution["id"]),),
        )
        conn.commit()

        vintage = lock_plan_execution(conn, str(execution["id"]))
        conn.commit()
        assert vintage["execution_target"] is None
        requirement_ids = [case["requirement_id"] for case in vintage["roster"]]
        with pytest.raises(
            QaPlanExecutionStateError, match="lacks an execution target"
        ):
            advance_plan_execution(
                conn,
                vintage,
                ordinal=1,
                requirement_id=requirement_ids[1],
                result={"requirement_id": requirement_ids[1], "verdict": "pass"},
            )
        conn.rollback()

        settled = lock_plan_execution(conn, str(execution["id"]))
        finish_plan_execution(
            conn, settled, state="aborted", reason="operator settlement"
        )
        assert settled["state"] == "aborted"
