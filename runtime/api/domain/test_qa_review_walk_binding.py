"""A pending QA review answers for its own originating walk, not any walk.

Two executions can touch the same requirement over time. Whether a review
request is disposed of must turn on the specific execution whose durable
result actually recorded that run -- an unrelated execution completing or
being abandoned, before or after, must not decide the fate of a review it
had nothing to do with.
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


def _undetermined_run(conn, *, requirement_id: int) -> int:
    return conn.execute(
        "INSERT INTO qa_runs "
        "(qa_requirement_id, performed_by, qa_kind, verdict, verdict_reason, "
        "started_at, completed_at, created_at) "
        "VALUES (%s, 'agent', 'plan_case', 'undetermined', "
        "'The walker never reached the surface.', "
        "'2026-06-01T00:00:00Z', '2026-06-01T00:00:00Z', "
        "'2026-06-01T00:00:00Z') RETURNING id",
        (requirement_id,),
    ).fetchone()[0]


def test_a_later_abandoned_walk_disposes_its_own_review_despite_an_older_completed_walk() -> (
    None
):
    """An unrelated earlier completion must not mask a later walk's abandonment.

    Execution A finishes cleanly and has nothing to do with the case under
    test. Execution B is the one whose durable result actually records the
    reviewed run, and B is the one that gets cut short -- so the review
    must be disposed on B's abandonment, regardless of A's unrelated,
    completed history on the same requirement.
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

        later = begin_plan_execution(
            conn,
            item_id=4812,
            transition_id="implemented",
            actor_id="7",
            session_id="later-walk-session",
        )
        run_id = _undetermined_run(conn, requirement_id=first_id)
        advance_plan_execution(
            conn,
            later,
            ordinal=0,
            requirement_id=first_id,
            result={
                "requirement_id": first_id,
                "verdict": "undetermined",
                "run_id": int(run_id),
            },
        )
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
        run_id = _undetermined_run(conn, requirement_id=first_id)
        advance_plan_execution(
            conn,
            older,
            ordinal=0,
            requirement_id=first_id,
            result={
                "requirement_id": first_id,
                "verdict": "undetermined",
                "run_id": int(run_id),
            },
        )
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


def test_an_unrelated_execution_completing_after_the_run_still_cannot_answer_for_it() -> (
    None
):
    """A later, unrelated completion is not evidence either -- identity, not time.

    Execution B raises the review and is abandoned without B's own
    termination disposing it (mirroring an operator settling the row by
    hand, the same shape ``test_the_sweep_converges_a_walk_that_already_ended``
    covers). Execution C starts after B's run was recorded and completes
    normally, but C never records B's run on any case of its own. A
    timestamp-only check would read C's later completion as fresh evidence
    for B's review and leave it pending forever; identity binding must
    still dispose it on convergence because C never touched this run.
    """
    with test_database() as conn:
        requirement_ids = _materialize_two_cases(conn, item_id=4814)
        first_id, second_id = requirement_ids

        cut_short = begin_plan_execution(
            conn,
            item_id=4814,
            transition_id="implemented",
            actor_id="7",
            session_id="cut-short-session",
        )
        run_id = _undetermined_run(conn, requirement_id=first_id)
        advance_plan_execution(
            conn,
            cut_short,
            ordinal=0,
            requirement_id=first_id,
            result={
                "requirement_id": first_id,
                "verdict": "undetermined",
                "run_id": int(run_id),
            },
        )
        request, _created = ensure_qa_review_request(
            conn, requirement_id=int(first_id), run_id=int(run_id)
        )
        request_id = int(request["id"])
        # Terminate the row the way a hand settlement does: no disposition,
        # so the review is still pending when the unrelated walk below runs.
        conn.execute(
            "UPDATE qa_plan_executions SET state='aborted',"
            "completed_at='2026-06-02T00:00:00Z' WHERE id=%s",
            (str(cut_short["id"]),),
        )
        conn.commit()
        assert _status(conn, request_id)[0] == "pending"

        # A second, unrelated walk starts and finishes strictly after the
        # abandoned run above was recorded -- chronologically later evidence
        # a timestamp-only check would have wrongly credited to B's review.
        unrelated = begin_plan_execution(
            conn,
            item_id=4814,
            transition_id="implemented",
            actor_id="7",
            session_id="unrelated-later-session",
        )
        for requirement_id in (first_id, second_id):
            advance_plan_execution(
                conn,
                unrelated,
                ordinal=unrelated["cursor_ordinal"],
                requirement_id=requirement_id,
                result={"requirement_id": requirement_id, "verdict": "pass"},
            )
        # The unrelated execution's own completion opportunistically retries
        # disposal for every requirement its roster touched, including this
        # one -- but the actual "ended" verdict still resolves through
        # identity to the aborted originator, not through unrelated's own
        # later completed_at, so it correctly withdraws here already.
        finish_plan_execution(conn, unrelated, state="completed", reason="clean walk")
        assert _status(conn, request_id)[0] == "withdrawn"

        # Convergence finds nothing left to do.
        result = dispose_ended_decision_requests(conn)
        assert request_id not in [row["request_id"] for row in result["withdrawn"]]
