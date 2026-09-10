"""A pending QA review answers for its own originating walk, not any walk.

Two executions can touch the same requirement over time. Whether a review
request is disposed of must turn on the specific execution that raised it --
an unrelated execution completing or being abandoned, before or after, must
not decide the fate of a review it had nothing to do with.
"""

from __future__ import annotations

from runtime.api.domain.test_qa_execution_decision_disposition import _status
from runtime.api.domain.test_qa_plan_execution_authority import (
    _materialize_two_cases,
)
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain.decision_request_disposition import (
    dispose_ended_decision_requests,
)
from yoke_core.domain.qa_plan_execution_state import (
    advance_plan_execution,
    begin_plan_execution,
    finish_plan_execution,
)
from yoke_core.domain.qa_review_requests import ensure_qa_review_request


def test_a_later_abandoned_walk_disposes_its_own_review_despite_an_older_completed_walk() -> (
    None
):
    """An unrelated earlier completion must not mask a later walk's abandonment.

    Execution A finishes cleanly and has nothing to do with the case under
    test. Execution B is the one that actually raises the review, and B is
    the one that gets cut short -- so the review must be disposed on B's
    abandonment, regardless of A's unrelated, older completion.
    """
    with test_database() as conn:
        requirement_ids = _materialize_two_cases(conn, item_id=4812)
        first_id, second_id = requirement_ids

        older = begin_plan_execution(
            conn,
            item_id=4812,
            transition_id="implemented",
            actor_id="7",
            session_id="older-walk-session",
        )
        for requirement_id in (first_id, second_id):
            advance_plan_execution(
                conn,
                older,
                ordinal=older["cursor_ordinal"],
                requirement_id=requirement_id,
                result={"requirement_id": requirement_id, "verdict": "pass"},
            )
        finish_plan_execution(conn, older, state="completed", reason="clean walk")
        conn.execute(
            "UPDATE qa_plan_executions SET completed_at='2026-01-01T00:00:00Z' "
            "WHERE id=%s",
            (str(older["id"]),),
        )
        conn.commit()

        later = begin_plan_execution(
            conn,
            item_id=4812,
            transition_id="implemented",
            actor_id="7",
            session_id="later-walk-session",
        )
        advance_plan_execution(
            conn,
            later,
            ordinal=0,
            requirement_id=first_id,
            result={"requirement_id": first_id, "verdict": "undetermined"},
        )
        run_id = conn.execute(
            "INSERT INTO qa_runs "
            "(qa_requirement_id, performed_by, qa_kind, verdict, verdict_reason, "
            "started_at, completed_at, created_at) "
            "VALUES (%s, 'agent', 'plan_case', 'undetermined', "
            "'The walker never reached the surface.', "
            "'2026-06-01T00:00:00Z', '2026-06-01T00:00:00Z', "
            "'2026-06-01T00:00:00Z') RETURNING id",
            (first_id,),
        ).fetchone()[0]
        request, _created = ensure_qa_review_request(
            conn, requirement_id=int(first_id), run_id=int(run_id)
        )
        request_id = int(request["id"])
        finish_plan_execution(
            conn, later, state="aborted", reason="the later walk was cut short"
        )

        # The abort settles it immediately (its own raised review, an
        # unrelated older completion notwithstanding); convergence then
        # finds nothing left to do.
        assert _status(conn, request_id)[0] == "withdrawn"
        result = dispose_ended_decision_requests(conn)
        assert request_id not in [row["request_id"] for row in result["withdrawn"]]


def test_an_older_completed_walks_review_survives_an_unrelated_later_abandoned_walk() -> (
    None
):
    """The converse: a later, unrelated abandonment must not erase a valid review."""
    with test_database() as conn:
        requirement_ids = _materialize_two_cases(conn, item_id=4813)
        first_id, second_id = requirement_ids

        older = begin_plan_execution(
            conn,
            item_id=4813,
            transition_id="implemented",
            actor_id="7",
            session_id="older-walk-session",
        )
        advance_plan_execution(
            conn,
            older,
            ordinal=0,
            requirement_id=first_id,
            result={"requirement_id": first_id, "verdict": "undetermined"},
        )
        run_id = conn.execute(
            "INSERT INTO qa_runs "
            "(qa_requirement_id, performed_by, qa_kind, verdict, verdict_reason, "
            "started_at, completed_at, created_at) "
            "VALUES (%s, 'agent', 'plan_case', 'undetermined', "
            "'The walker never reached the surface.', "
            "'2026-06-01T00:00:00Z', '2026-06-01T00:00:00Z', "
            "'2026-06-01T00:00:00Z') RETURNING id",
            (first_id,),
        ).fetchone()[0]
        request, _created = ensure_qa_review_request(
            conn, requirement_id=int(first_id), run_id=int(run_id)
        )
        request_id = int(request["id"])
        advance_plan_execution(
            conn,
            older,
            ordinal=1,
            requirement_id=second_id,
            result={"requirement_id": second_id, "verdict": "pass"},
        )
        finish_plan_execution(conn, older, state="completed", reason="clean walk")

        later = begin_plan_execution(
            conn,
            item_id=4813,
            transition_id="implemented",
            actor_id="7",
            session_id="later-walk-session",
        )
        advance_plan_execution(
            conn,
            later,
            ordinal=0,
            requirement_id=first_id,
            result={"requirement_id": first_id, "verdict": "pass"},
        )
        finish_plan_execution(
            conn, later, state="aborted", reason="an unrelated later walk was cut short"
        )

        result = dispose_ended_decision_requests(conn)

        assert _status(conn, request_id)[0] == "pending"
        assert request_id not in [row["request_id"] for row in result["withdrawn"]]
