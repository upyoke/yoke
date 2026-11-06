"""Verdict entry points bind proof before the production PostgreSQL trigger freezes it."""

import json

import psycopg
import pytest

from runtime.api.domain.deployment_qa_run_settlement_test_support import (
    exercise_late_verdict,
)
from runtime.api.fixtures.qa_captured_plan_review_fixture import captured_plan_review
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers.qa_plan_review import (
    handle_plan_review_begin,
    handle_plan_review_submit,
)


def _assert_frozen(conn, run_id):
    before = conn.execute(
        "SELECT raw_result FROM qa_runs WHERE id=%s", (run_id,)
    ).fetchone()[0]
    conn.execute("SAVEPOINT immutable_proof")
    with pytest.raises(psycopg.errors.RaiseException, match="immutable once verdict"):
        conn.execute(
            "UPDATE qa_runs SET raw_result=%s WHERE id=%s", ('{"changed":true}', run_id)
        )
    conn.execute("ROLLBACK TO SAVEPOINT immutable_proof")
    assert (
        conn.execute(
            "SELECT raw_result FROM qa_runs WHERE id=%s", (run_id,)
        ).fetchone()[0]
        == before
    )


def test_record_verdict_binds_aggregate_evidence_before_freeze(test_db):
    # Exercises the actual record_verdict handler, artifact binding, and late
    # server-side stage acceptance with the production trigger installed.
    exercise_late_verdict(test_db)
    run_id = test_db.execute(
        "SELECT id FROM qa_runs WHERE performed_by='agent' ORDER BY id DESC LIMIT 1"
    ).fetchone()[0]
    _assert_frozen(test_db, run_id)


def test_plan_review_submit_binds_capture_evidence_before_freeze(test_db):
    execution, requirement, capture = captured_plan_review(test_db, 9789)
    raw = json.loads(
        test_db.execute(
            "SELECT raw_result FROM qa_runs WHERE id=%s", (capture,)
        ).fetchone()[0]
    )
    # A capture written before evidence binding existed still requires safe
    # enrichment in the same write that first judges it.
    raw.pop("execution_id", None)
    raw.pop("evidence_artifact_ids", None)
    test_db.execute(
        "UPDATE qa_runs SET raw_result=%s WHERE id=%s", (json.dumps(raw), capture)
    )
    test_db.commit()
    actor = ActorContext(actor_id="7", session_id="review-session")
    target = TargetRef(kind="item", item_id=9789)
    begun = handle_plan_review_begin(
        FunctionCallRequest(
            function="qa.plan_review.begin",
            actor=actor,
            target=target,
            payload={"execution_id": execution["id"]},
        )
    )
    assert begun.primary_success, begun.error
    bundle = begun.result_payload["review_bundle"]
    payload = {
        "execution_id": execution["id"],
        "bundle_id": bundle["bundle_id"],
        "bundle_digest": bundle["bundle_digest"],
        "verdicts": [
            {
                "requirement_id": requirement,
                "verdict": "pass",
                "rationale": "The captured project frame is correct.",
            }
        ],
    }
    for _ in range(2):
        submitted = handle_plan_review_submit(
            FunctionCallRequest(
                function="qa.plan_review.submit",
                actor=actor,
                target=target,
                payload=payload,
            )
        )
        assert submitted.primary_success, submitted.error
    verdict, stored = test_db.execute(
        "SELECT verdict,raw_result FROM qa_runs WHERE id=%s", (capture,)
    ).fetchone()
    proof = json.loads(stored)
    assert verdict == "pass"
    assert proof["execution_id"] == execution["id"]
    assert proof["evidence_artifact_ids"]
    assert proof["evidence"] == raw["evidence"]
    _assert_frozen(test_db, capture)
