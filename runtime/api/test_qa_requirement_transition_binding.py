"""Lifecycle binding on the typed QA requirement authoring surface."""

from __future__ import annotations

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.pg_testdb import test_database
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers.qa_requirement_create import (
    handle_qa_requirement_add,
)
from yoke_core.domain.item_posture_bindings import (
    ITEM_POSTURE_VERIFICATION_TRANSITION,
)


def _request(item_id: int, transition_id: str) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="qa.requirement.add",
        actor=ActorContext(actor_id="1", session_id="dash-session"),
        target=TargetRef(kind="item", item_id=item_id),
        payload={
            "method_id": "browser-check",
            "qa_phase": "verification",
            "instructions": "Inspect the workflow card in its actual route.",
            "expected_outcome": "The workflow card matches its visual contract.",
            "method_config": {
                "steps": [
                    {"action": "navigate", "route": "/workflows"},
                    {
                        "action": "assert",
                        "target": "main",
                        "check": "visible",
                    },
                ],
            },
            "workflow_transition_id": transition_id,
        },
    )


def test_requirement_persists_a_valid_pinned_workflow_transition():
    with test_database() as conn:
        insert_item(conn, id=2401, workflow_id="dash")
        outcome = handle_qa_requirement_add(
            _request(
                2401,
                f" {ITEM_POSTURE_VERIFICATION_TRANSITION} ",
            ),
        )
        assert outcome.primary_success is True
        row = conn.execute(
            "SELECT workflow_transition_id FROM qa_requirements WHERE id=%s",
            (outcome.result_payload["requirement_id"],),
        ).fetchone()
    assert row[0] == ITEM_POSTURE_VERIFICATION_TRANSITION


def test_requirement_rejects_a_transition_outside_the_pinned_workflow():
    with test_database() as conn:
        insert_item(conn, id=2402, workflow_id="dash")
        outcome = handle_qa_requirement_add(
            _request(2402, "reviewed-implementation"),
        )
    assert outcome.primary_success is False
    assert outcome.error.code == "payload_invalid"
    assert outcome.error.jsonpath == "$.payload.workflow_transition_id"
