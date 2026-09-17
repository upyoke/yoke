"""Post-merge QA phases cannot bind to a pre-release review stage."""

from __future__ import annotations

import json

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
from yoke_core.domain.qa_workflow_binding_validation import (
    ITEM_POSTURE_VERIFICATION_TRANSITION,
)


POSTURE = {"verification": {"kind": "ad_hoc", "method_id": "browser-check"}}


def _request(item_id: int, *, phase: str, transition: str) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="qa.requirement.add",
        actor=ActorContext(actor_id="1", session_id="dash-session"),
        target=TargetRef(kind="item", item_id=item_id),
        payload={
            "method_id": "browser-check",
            "qa_phase": phase,
            "instructions": "Capture the deployed surface.",
            "expected_outcome": "The deployed surface matches the request.",
            "method_config": {
                "steps": [
                    {"action": "navigate", "route": "/"},
                    {"action": "assert", "target": "main", "check": "visible"},
                ]
            },
            "workflow_transition_id": transition,
        },
    )


def test_post_deploy_cannot_bind_to_the_review_transition():
    with test_database() as conn:
        insert_item(
            conn,
            id=2501,
            workflow_id="dash",
            workflow_posture=json.dumps(POSTURE),
        )
        outcome = handle_qa_requirement_add(
            _request(
                2501,
                phase="post_deploy",
                transition=ITEM_POSTURE_VERIFICATION_TRANSITION,
            )
        )
    assert outcome.primary_success is False
    assert outcome.error.code == "payload_invalid"
    assert "post-deployment acceptance" in outcome.error.message
    assert "--workflow-transition release" in outcome.error.message
    assert "--deployment-run" in outcome.error.message


def test_post_deploy_binds_to_the_pinned_release_wait():
    with test_database() as conn:
        insert_item(
            conn,
            id=2502,
            workflow_id="dash",
            workflow_posture=json.dumps(POSTURE),
        )
        outcome = handle_qa_requirement_add(
            _request(2502, phase="post_deploy", transition="release")
        )
        assert outcome.primary_success is True
        row = conn.execute(
            "SELECT workflow_transition_id, qa_phase FROM qa_requirements "
            "WHERE id=%s",
            (outcome.result_payload["requirement_id"],),
        ).fetchone()
    assert row[0] == "release"
    assert row[1] == "post_deploy"


def test_verification_still_binds_to_the_review_transition():
    with test_database() as conn:
        insert_item(
            conn,
            id=2503,
            workflow_id="dash",
            workflow_posture=json.dumps(POSTURE),
        )
        outcome = handle_qa_requirement_add(
            _request(
                2503,
                phase="verification",
                transition=ITEM_POSTURE_VERIFICATION_TRANSITION,
            )
        )
    assert outcome.primary_success is True
