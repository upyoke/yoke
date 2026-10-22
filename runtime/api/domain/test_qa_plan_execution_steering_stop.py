"""A steering seat stops another session's live QA walk through its runner.

The stop records the existing stop request rather than settling the row, so
the owning runner -- the only process that can clean up its host -- stops
at its next check-in and settles the execution itself.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from runtime.api.domain.deployment_run_qa_plan_execution_test_support import (
    RUN_ID,
    command_plan,
    deployment_run,
)
from runtime.api.fixtures.session_holdings import insert_steering_claim
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers.qa_plan_execution import (
    handle_plan_execution_abort,
    handle_plan_execution_heartbeat,
)
from yoke_core.domain.qa_plan_attachments import materialize_for_deployment_run
from yoke_core.domain.qa_plan_execution_abort_state import abort_request
from yoke_core.domain.qa_plan_execution_run import execute_begun_plan
from yoke_core.domain.qa_plan_execution_state import (
    begin_plan_execution,
    lock_plan_execution,
)

OWNER = ActorContext(actor_id="7", session_id="qa-owner")
STEERER = ActorContext(actor_id="2", session_id="steering-seat")
BYSTANDER = ActorContext(actor_id="3", session_id="no-seat")


@pytest.fixture
def live_execution(test_db) -> str:
    deployment_run(test_db)
    command_plan(test_db)
    materialize_for_deployment_run(
        test_db, deployment_run_id=RUN_ID, plan="deployment-smoke", project="yoke"
    )
    execution = begin_plan_execution(
        test_db,
        deployment_run_id=RUN_ID,
        actor_id=OWNER.actor_id,
        session_id=OWNER.session_id,
    )
    return str(execution["id"])


def _call(handler, actor, execution_id, **payload):
    return handler(
        FunctionCallRequest(
            function="qa.plan_execution.abort",
            actor=actor,
            target=TargetRef(kind="global", project_id="yoke"),
            payload={"execution_id": execution_id, **payload},
        )
    )


def test_steering_seat_records_a_stop_the_owners_check_in_settles(
    test_db, live_execution
):
    insert_steering_claim(test_db, STEERER.session_id, project_id=1)

    stopped = _call(
        handle_plan_execution_abort, STEERER, live_execution, reason="redundant rerun"
    )

    assert stopped.primary_success, stopped.error
    receipt = stopped.result_payload["stop_request"]
    assert receipt["outcome"] == "stop_requested"
    assert receipt["owner_session_id"] == OWNER.session_id
    assert "next case check-in or host heartbeat" in receipt["next"]
    execution = lock_plan_execution(test_db, live_execution)
    test_db.rollback()
    assert execution["state"] == "active"
    request = abort_request(execution)
    assert request["requested_by_session_id"] == STEERER.session_id
    assert request["requested_by_actor_id"] == STEERER.actor_id
    assert request["reason"] == (
        "steering-stop-requested: session steering-seat: redundant rerun"
    )

    checked = _call(handle_plan_execution_heartbeat, OWNER, live_execution)
    assert checked.primary_success, checked.error
    assert checked.result_payload["abort_requested"] is True

    settled = _call(
        handle_plan_execution_abort, OWNER, live_execution, reason="runner stopped"
    )
    assert settled.primary_success, settled.error
    assert settled.result_payload["state"] == "aborted"
    assert settled.result_payload["release_reason"].startswith(request["reason"])


def test_caller_without_a_seat_is_refused_with_the_steering_path(
    test_db, live_execution
):
    refused = _call(
        handle_plan_execution_abort, BYSTANDER, live_execution, reason="stop it"
    )

    assert not refused.primary_success
    message = refused.error.message
    assert message.startswith("qa_execution_stop_requires_steering:")
    assert "yoke claims steering acquire --project 1" in message
    execution = lock_plan_execution(test_db, live_execution)
    test_db.rollback()
    assert execution["state"] == "active"
    assert abort_request(execution) is None


def test_owner_abort_settles_under_its_own_reason(test_db, live_execution):
    aborted = _call(
        handle_plan_execution_abort, OWNER, live_execution, reason="owner stop"
    )

    assert aborted.primary_success, aborted.error
    assert aborted.result_payload["state"] == "aborted"
    assert aborted.result_payload["release_reason"].startswith("owner stop;")
    assert "stop_request" not in aborted.result_payload


def test_runner_aborts_its_execution_when_a_check_in_reports_a_stop():
    calls = []

    def call_plan_function(*, function_id, target, payload, actor):
        calls.append(function_id)
        if function_id == "qa.plan_execution.heartbeat":
            return {"abort_requested": True, "roster_digest": "digest"}
        return {"execution_id": "e1", "state": "aborted"}

    begun = SimpleNamespace(
        requirements=[
            {
                "requirement_id": 11,
                "runner_id": "worktree_run",
                "case_key": "smoke",
                "case_position": 0,
                "baseline_position": 0,
            }
        ],
        cursor=0,
        resolved_base_url=None,
        recorded_results=[],
        recorded_ordinals=[],
        selected_machine=None,
        host_free_cases_ahead=False,
    )
    result = execute_begun_plan(
        execution={"execution_id": "e1", "roster_digest": "digest"},
        begun=begun,
        target=None,
        resolved_actor=None,
        transition_id=None,
        expected_branch=None,
        expected_sha=None,
        timeout_seconds=1,
        checkout_path=None,
        allow_tree_mismatch=False,
        call_plan_function=call_plan_function,
    )

    assert calls == ["qa.plan_execution.heartbeat", "qa.plan_execution.abort"]
    assert result["state"] == "error"
    assert "qa_stop_requested" in result["results"][0]["error"]
