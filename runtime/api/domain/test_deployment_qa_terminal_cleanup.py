"""Failed deployment runs retain the owner's abort and mission teardown paths."""

from types import SimpleNamespace

import pytest

from runtime.api.domain import test_agent_mission_cleanup as mission_support
from runtime.api.domain.test_deployment_qa_stage_execution import (
    _plan,
    _seed_run,
    _stages,
)
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.agent_mission_recording import handle_agent_mission_access
from yoke_contracts.qa_mission_scratch import mission_scratch_path
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.coordination_claims import get_claim
from yoke_core.domain.handlers.qa_plan_execution import handle_plan_execution_abort
from yoke_core.domain.qa_deployment_function_subject import resolve_run_qa_subject
from yoke_core.domain.qa_plan_execution_state import (
    begin_plan_execution,
    lock_plan_execution,
)


terminal_mission = mission_support.removed_mission


@pytest.fixture
def deployment_execution(test_db):
    run_id = "run-abort-after-failure"
    _seed_run(test_db, run_id=run_id, stages=_stages(_plan(test_db)), members=(9701,))
    materialize_deployment_qa_stage(
        test_db,
        deployment_run_id=run_id,
        deployment_stage="item-qa",
        deployment_member_item_id=9701,
    )
    execution = begin_plan_execution(
        test_db,
        deployment_run_id=run_id,
        deployment_stage="item-qa",
        deployment_member_item_id=9701,
        actor_id="2",
        session_id="qa-owner",
    )
    test_db.execute("UPDATE deployment_runs SET status='failed' WHERE id=%s", (run_id,))
    test_db.commit()
    request = FunctionCallRequest(
        function="qa.plan_execution.abort",
        actor=ActorContext(actor_id="2", session_id="qa-owner"),
        target=TargetRef(
            kind="deployment_run", deployment_run_id=run_id, project_id="yoke"
        ),
        payload={"execution_id": execution["id"], "reason": "stop failed run"},
    )
    return request


def test_owner_aborts_after_run_failure_and_records_status(
    test_db, deployment_execution
):
    request = deployment_execution
    assert resolve_run_qa_subject(test_db, request) == (1, "yoke", 9701)
    outcome = handle_plan_execution_abort(request)
    assert outcome.primary_success, outcome.error
    assert outcome.result_payload["state"] == "aborted"
    execution = lock_plan_execution(test_db, request.payload["execution_id"])
    assert (
        execution["release_reason"] == "stop failed run; deployment run status=failed"
    )


@pytest.mark.parametrize("state", ["aborted", "completed", "error"])
def test_settled_execution_reports_state_without_active_stage_recovery(
    test_db, deployment_execution, state
):
    request = deployment_execution
    test_db.execute(
        "UPDATE qa_plan_executions SET state=%s WHERE id=%s",
        (state, request.payload["execution_id"]),
    )
    test_db.commit()
    assert resolve_run_qa_subject(test_db, request) == (1, "yoke", 9701)
    outcome = handle_plan_execution_abort(request)
    if state == "aborted":
        assert outcome.primary_success, outcome.error
        assert outcome.result_payload["state"] == state
    else:
        assert not outcome.primary_success
        assert f"already terminal as '{state}'" in outcome.error.message
        assert "active" not in outcome.error.message


def test_terminal_run_keeps_other_writes_and_other_sessions_guarded(
    test_db, deployment_execution
):
    request = deployment_execution
    with pytest.raises(ValueError, match="active stage"):
        resolve_run_qa_subject(
            test_db,
            request.model_copy(update={"function": "qa.plan_execution.advance"}),
        )
    other = request.model_copy(
        update={"actor": ActorContext(actor_id="2", session_id="other-session")}
    )
    outcome = handle_plan_execution_abort(other)
    assert not outcome.primary_success
    assert "still reporting progress" in outcome.error.message


@pytest.mark.parametrize("terminal_mission", ["failed", "cancelled"], indirect=True)
def test_terminal_run_walk_end_restores_scratch_and_releases_lease(
    test_db, monkeypatch, terminal_mission
):
    from yoke_core.domain import machine_qa_mission_walk
    from yoke_core.domain.machine_qa_mission_walk import execute_agent_mission_walk_end
    from yoke_core.domain.yoke_function_dispatch_qa_claims import (
        qa_subject_claim_verdict,
    )

    request, control, original = terminal_mission
    assert qa_subject_claim_verdict(request) == (True, None, None)
    assert resolve_run_qa_subject(test_db, request) == (1, "yoke", 7841)
    acquired = handle_agent_mission_access(request)
    assert acquired.primary_success, acquired.error
    contract = acquired.result_payload["execution"]
    assert contract["lease_id"] == original["lease_id"]
    restored = []
    monkeypatch.setattr(
        machine_qa_mission_walk,
        "_execution",
        lambda c: SimpleNamespace(
            control=control,
            material=SimpleNamespace(secrets={}),
            reach_baseline=lambda name: (
                restored.append(name)
                or SimpleNamespace(ok=True, error_code=None, evidence={})
            ),
        ),
    )
    result = execute_agent_mission_walk_end(contract)
    assert result["removed"] and result["starting_state_restore"]["restored"]
    assert not any(
        p.startswith(mission_scratch_path(request.payload["execution_id"]))
        for p in control.existing_paths
    )
    assert restored == ["fresh-host"]
    finished = handle_agent_mission_access(
        request.model_copy(
            update={
                "payload": {
                    **request.payload,
                    "cleanup": "finish",
                    "lease_id": contract["lease_id"],
                    "restore": result["starting_state_restore"],
                }
            }
        )
    )
    assert finished.primary_success, finished.error
    assert not get_claim(test_db, contract["lease_id"]).is_active
    execution = lock_plan_execution(test_db, request.payload["execution_id"])
    assert execution["state"] == "aborted" and execution["machine_lease_id"] is None
    assert "deployment run status=" in execution["release_reason"]


@pytest.mark.parametrize("terminal_mission", ["failed"], indirect=True)
@pytest.mark.parametrize("change", ["actor", "session", "subject"])
def test_failed_run_cleanup_requires_original_owner_and_subject(
    terminal_mission, change
):
    request, _, _ = terminal_mission
    if change == "subject":
        request = request.model_copy(
            update={
                "target": TargetRef(
                    kind="deployment_run", deployment_run_id="another-run"
                )
            }
        )
    else:
        request = request.model_copy(
            update={
                "actor": ActorContext(
                    actor_id="99" if change == "actor" else request.actor.actor_id,
                    session_id="other-session"
                    if change == "session"
                    else request.actor.session_id,
                )
            }
        )
    assert not handle_agent_mission_access(request).primary_success
