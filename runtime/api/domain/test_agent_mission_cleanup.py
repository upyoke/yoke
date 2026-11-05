"""Removed missions keep their host for owner-only teardown without reviving their walk."""

from runtime.api.domain.agent_mission_cleanup_test_support import (
    ITEM as ITEM,
    RUN as RUN,
    removed_mission as removed_mission,
)


from types import SimpleNamespace

import pytest

from runtime.api.domain.agent_mission_qa_test_support import (
    ACTOR,
)
from yoke_contracts.api.function_call import ActorContext
from yoke_contracts.qa_mission_scratch import mission_scratch_path
from yoke_core.domain.agent_mission_recording import (
    handle_agent_mission_access,
)
from yoke_core.domain.coordination_claims import (
    CoordinationClaimHeldError,
    acquire,
    get_claim,
)
from yoke_core.domain.machine_qa_mission_walk import execute_agent_mission_walk_end
from yoke_core.domain.qa_plan_execution_state import (
    lock_plan_execution,
)
from yoke_core.domain.qa_plan_execution_lifecycle import finish_plan_execution
from yoke_core.domain.qa_plan_execution_store import QaPlanExecutionStateError
from yoke_core.domain.work_claim_targets import make_qa_admission_target


def test_removed_member_walk_end_clears_staged_secrets_and_restores_start(
    test_db, monkeypatch, removed_mission
):
    from yoke_core.domain import machine_qa_mission_walk
    from yoke_core.domain.qa_deployment_function_subject import resolve_run_qa_subject
    from yoke_core.domain.qa_execution_request_identity import resolve_execution_request
    from yoke_core.domain.yoke_function_dispatch_qa_claims import (
        qa_subject_claim_verdict,
    )

    request, control, original = removed_mission
    assert qa_subject_claim_verdict(request) == (True, None, None)
    assert resolve_run_qa_subject(
        test_db, resolve_execution_request(test_db, request)
    ) == (1, "yoke", ITEM)
    acquired = handle_agent_mission_access(request)
    assert acquired.primary_success, acquired.error
    contract = acquired.result_payload["execution"]
    assert (
        contract["settings"]["resource_name"] == original["settings"]["resource_name"]
    )
    assert contract["lease_id"] == original["lease_id"]
    restored = []

    def restore(name):
        assert not any(
            p.startswith(mission_scratch_path(request.payload["execution_id"]))
            for p in control.existing_paths
        )
        restored.append(name)
        return SimpleNamespace(ok=True, error_code=None, evidence={})

    monkeypatch.setattr(
        machine_qa_mission_walk,
        "_execution",
        lambda c: SimpleNamespace(
            control=control,
            material=SimpleNamespace(secrets={}),
            reach_baseline=restore,
        ),
    )
    result = execute_agent_mission_walk_end(contract)
    assert result["removed"]
    assert result["starting_state_restore"]["restored"]
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
    current = lock_plan_execution(test_db, request.payload["execution_id"])
    assert current["state"] == "aborted" and current["test_machine_lease_id"] is None
    assert current["release_reason"] == "deployment-member-removed"
    assert (
        test_db.execute(
            "SELECT count(*) FROM qa_artifacts WHERE qa_run_id=%s "
            "AND artifact_type='starting_state_restore'",
            (request.payload["run_id"],),
        ).fetchone()[0]
        == 1
    )


@pytest.mark.parametrize("change", ["session", "actor", "run", "requirement", "walk"])
def test_cleanup_refuses_wrong_owner_docket_and_normal_walk(removed_mission, change):
    request, _, _ = removed_mission
    if change in {"session", "actor"}:
        request = request.model_copy(
            update={
                "actor": ActorContext(
                    actor_id="2" if change == "actor" else ACTOR.actor_id,
                    session_id="other-session"
                    if change == "session"
                    else ACTOR.session_id,
                )
            }
        )
    else:
        payload = dict(request.payload)
        if change == "walk":
            payload.pop("cleanup")
            payload.pop("run_id")
        else:
            payload["run_id" if change == "run" else "requirement_id"] += 1
        request = request.model_copy(update={"payload": payload})
    outcome = handle_agent_mission_access(request)
    assert not outcome.primary_success


def test_removed_mission_host_is_held_until_walk_end(removed_mission, test_db):
    request, _, original = removed_mission
    host = original["settings"]["resource_name"]
    with pytest.raises(CoordinationClaimHeldError):
        acquire(
            test_db,
            make_qa_admission_target(host),
            "another-session",
            reason="another execution",
        )
    test_db.rollback()
    execution = lock_plan_execution(test_db, request.payload["execution_id"])
    with pytest.raises(QaPlanExecutionStateError, match="qa_abort_walk_end_required"):
        finish_plan_execution(test_db, execution, state="aborted", reason="operator")
    test_db.rollback()
    walk = dict(request.payload)
    walk.pop("cleanup")
    walk.pop("run_id")
    refused = handle_agent_mission_access(request.model_copy(update={"payload": walk}))
    assert "mission_member_removed" in refused.error.message
    acquired = handle_agent_mission_access(request)
    assert acquired.primary_success, acquired.error
    replay = handle_agent_mission_access(request)
    assert replay.primary_success, replay.error
    assert replay.result_payload["execution"]["lease_id"] == original["lease_id"]
    assert get_claim(test_db, original["lease_id"]).is_active
