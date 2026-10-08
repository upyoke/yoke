"""A review judges its capture without manufacturing another execution."""

import pytest

from runtime.api.domain.test_qa_plan_agent_review import _review_execution
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain.qa_capture_settlement import stamp_reviewed_capture
from yoke_core.domain.qa_plan_review import begin_plan_review
from yoke_core.domain.qa_plan_review_submission import submit_plan_review


def test_review_preserves_attempt_count_start_and_evidence():
    with test_database() as conn:
        execution, requirement_id, capture_id = _review_execution(conn, 4581)
        before = conn.execute(
            "SELECT started_at,raw_result FROM qa_runs WHERE id=%s", (capture_id,)
        ).fetchone()
        bundle = begin_plan_review(conn, execution)
        arguments = dict(
            bundle_id=bundle["bundle_id"],
            bundle_digest=bundle["bundle_digest"],
            verdicts=[
                dict(
                    requirement_id=requirement_id,
                    verdict="pass",
                    rationale="The actual captured frame proves the outcome.",
                )
            ],
            reviewer_actor_id=None,
            reviewer_session_id="review-session",
        )
        first = submit_plan_review(conn, execution, **arguments)
        replay = submit_plan_review(conn, execution, **arguments)
        assert first["verdicts"] == replay["verdicts"]
        assert first["verdicts"][0]["review_run_id"] == capture_id
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM qa_runs WHERE qa_requirement_id=%s",
                (requirement_id,),
            ).fetchone()[0]
            == 1
        )
        after = conn.execute(
            "SELECT started_at,raw_result FROM qa_runs WHERE id=%s", (capture_id,)
        ).fetchone()
        assert tuple(after) == tuple(before)
        audit = conn.execute(
            "SELECT capture_run_id,review_run_id FROM qa_plan_review_verdicts "
            "WHERE bundle_id=%s",
            (bundle["bundle_id"],),
        ).fetchone()
        assert tuple(audit) == (capture_id, capture_id)


def test_capture_review_refuses_wrong_requirement_without_writes():
    with test_database() as conn:
        _execution, requirement_id, capture_id = _review_execution(conn, 4582)
        with pytest.raises(ValueError, match="qa_review_capture_mismatch"):
            stamp_reviewed_capture(
                conn,
                dict(requirement_id=requirement_id + 1, capture_run_id=capture_id),
                verdict="pass",
                rationale="Wrong subject",
                created_at="2026-07-30T00:00:00Z",
            )
        assert (
            conn.execute(
                "SELECT verdict FROM qa_runs WHERE id=%s", (capture_id,)
            ).fetchone()[0]
            is None
        )


@pytest.mark.parametrize("new_verdict", [None, "fail"])
def test_delayed_capture_review_cannot_discharge_newer_attempt(new_verdict):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from runtime.api.fixtures.pg_testdb import connect_test_database
    from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
        record_case_verdict,
        seed_member_qa_case,
    )
    from runtime.api.fixtures.qa_declared_replacement_fixture import (
        corrected_case,
        declare,
    )
    from yoke_core.domain.qa_run_verdict_record import insert_qa_run
    from yoke_core.domain.qa_latest_execution import latest_executions
    from yoke_core.domain.qa_requirement_pass_currency import has_current_passing_run

    with test_database() as conn:
        predecessor = seed_member_qa_case(
            conn, run_id="concurrent-review", member_item_id=9811
        )
        record_case_verdict(conn, predecessor, "fail", evidence=True)
        requirement = corrected_case(conn, failed_id=predecessor, case_key="corrected")
        declare(conn, predecessor, "corrected", [requirement])
        capture = insert_qa_run(
            conn,
            qa_requirement_id=requirement,
            performed_by="host_control",
            qa_kind="plan_case",
            verdict=None,
            started_at="2026-10-01T00:00:00Z",
            created_at="2026-10-01T00:00:00Z",
        ).run_id
        conn.commit()
        ready, new_committed = Barrier(2), Barrier(2)
        connections = [connect_test_database(conn.info.dbname) for _ in range(2)]

        def review():
            # Read the named capture before a concurrent new attempt exists.
            connections[0].execute(
                "SELECT id FROM qa_runs WHERE id=%s", (capture,)
            ).fetchone()
            ready.wait(timeout=30)
            new_committed.wait(timeout=30)
            result = stamp_reviewed_capture(
                connections[0],
                dict(requirement_id=requirement, capture_run_id=capture),
                verdict="pass",
                rationale="The older capture passed.",
                created_at="2026-10-01T00:00:02Z",
            )
            connections[0].commit()
            return result

        def execute():
            ready.wait(timeout=30)
            result = insert_qa_run(
                connections[1],
                qa_requirement_id=requirement,
                performed_by="host_control",
                qa_kind="plan_case",
                verdict=new_verdict,
                started_at="2026-10-01T00:00:01Z",
                completed_at="2026-10-01T00:00:01Z" if new_verdict else None,
                created_at="2026-10-01T00:00:01Z",
            )
            connections[1].commit()
            new_committed.wait(timeout=30)
            return result.run_id

        try:
            with ThreadPoolExecutor(max_workers=2) as workers:
                reviewed, executed = workers.submit(review), workers.submit(execute)
                assert reviewed.result(timeout=35).discharged == []
                newest = executed.result(timeout=35)
            assert latest_executions(conn, [requirement])[requirement]["id"] == newest
            assert not has_current_passing_run(conn, requirement)
            assert (
                conn.execute(
                    "SELECT verdict FROM qa_runs WHERE id=%s", (capture,)
                ).fetchone()[0]
                == "pass"
            )
            assert (
                conn.execute(
                    "SELECT superseded_by_requirement_id FROM qa_requirements WHERE id=%s",
                    (predecessor,),
                ).fetchone()[0]
                is None
            )
        finally:
            for connection in connections:
                connection.close()
