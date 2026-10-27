"""Reconciliation uses the execution item's current work claim."""

import pytest

from runtime.api.domain.test_qa_plan_execution_reconcile import (
    REASON,
    _awaiting_review,
    _stale,
)
from runtime.api.domain.test_qa_plan_retire import _handler_uses
from runtime.api.fixtures.dispatch_actor import register_session_actor
from runtime.api.fixtures.session_holdings import insert_item_claim
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers.qa_plan_execution_reconcile import (
    handle_execution_reconcile,
)
from yoke_core.domain.qa_plan_execution_store import lock_plan_execution


@pytest.mark.parametrize("claim_kind", ["own", "other", "released", "none"])
def test_handler_requires_owning_item_claim_without_seat(test_db, claim_kind):
    execution, bundle, _capture = _awaiting_review(test_db, 4951)
    actor_id = register_session_actor(test_db, "successor-session")
    if claim_kind != "none":
        item_id = 4951
        if claim_kind == "other":
            from runtime.api.fixtures.backlog_inserts import insert_item

            item_id = 4952
            insert_item(
                test_db, id=item_id, project_sequence=item_id, workflow_id="dash"
            )
        insert_item_claim(test_db, "successor-session", item_id)
        if claim_kind == "released":
            test_db.execute(
                "UPDATE work_claims SET released_at=CURRENT_TIMESTAMP "
                "WHERE session_id='successor-session'"
            )
    _stale(test_db, execution["id"])
    request = FunctionCallRequest(
        function="qa.plan_execution.reconcile",
        actor=ActorContext(actor_id=str(actor_id), session_id="successor-session"),
        target=TargetRef(kind="global", project_id="yoke"),
        payload={"execution_id": execution["id"], "reason": REASON},
    )
    with _handler_uses(test_db):
        outcome = handle_execution_reconcile(request)
    if claim_kind == "own":
        assert outcome.primary_success, outcome.error
        assert outcome.result_payload["outcome"] == "review_handoff"
        assert outcome.result_payload["review_bundle_id"] == bundle["bundle_id"]
        assert (
            lock_plan_execution(test_db, execution["id"])["session_id"]
            == "successor-session"
        )
    else:
        assert not outcome.primary_success
        assert outcome.error.code == "steering_seat_required"
        assert (
            lock_plan_execution(test_db, execution["id"])["session_id"]
            == execution["session_id"]
        )
