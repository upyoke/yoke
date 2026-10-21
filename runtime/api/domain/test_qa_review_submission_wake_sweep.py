"""Review submission withdraws the owner's review wakes after its verdicts commit."""

from __future__ import annotations

from runtime.api.domain.test_qa_capture_pending_review import _seed_pending, _submit
from runtime.api.domain.test_qa_plan_agent_review_wake import _owner
from runtime.api.fixtures.pg_testdb import connect_test_database
from yoke_core.domain import qa_plan_settled_review
from yoke_core.domain.qa_plan_settled_review import SETTLED_REVIEW_WAKE_REASON


def test_wake_sweep_runs_after_the_verdict_batch_is_committed(test_db, monkeypatch):
    _owner(test_db)
    execution, bundle, requirement_id = _seed_pending(
        test_db, "run-review-sweep-after-commit", "item"
    )
    withdraw = qa_plan_settled_review.withdraw_settled_agent_review_wakes
    observed: list[str] = []

    def withdraw_after_commit(conn, *, execution_id, **kwargs):
        other = connect_test_database(test_db.info.dbname)
        try:
            # Another connection sees the batch only once it is committed.
            row = other.execute(
                "SELECT state FROM qa_plan_review_bundles WHERE id=%s",
                (bundle["bundle_id"],),
            ).fetchone()
            observed.append(str(row[0]))
        finally:
            other.close()
        return withdraw(conn, execution_id=execution_id, **kwargs)

    monkeypatch.setattr(
        qa_plan_settled_review,
        "withdraw_settled_agent_review_wakes",
        withdraw_after_commit,
    )
    _submit(test_db, execution, bundle, requirement_id, "fail")

    assert observed == ["completed"]
    reason = test_db.execute(
        "SELECT cancellation_reason FROM session_messages WHERE idempotency_key=%s",
        (f"qa-plan-agent-review:{execution['id']}",),
    ).fetchone()[0]
    assert str(reason).startswith(SETTLED_REVIEW_WAKE_REASON)
