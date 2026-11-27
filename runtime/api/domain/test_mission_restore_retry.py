"""A recorded walk-end retry pays only the failed walk's own reset debt."""

import base64
import json

import pytest

from runtime.api.domain import agent_mission_qa_test_support as mission
from runtime.api.domain.machine_qa_session_seed import seed_registered_qa_launch
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_contracts.machine_qa_host_control import RESET_OWED_OPERATION
from yoke_core.domain.machine_idle_notice import (
    collect_released_hosts,
    released_reset_debts,
)
from yoke_core.domain.machine_operation_recording import recorded_test_machine_operation
from yoke_core.domain.machine_reset_debt import record_reset_owed, reset_owed
from runtime.api.domain.qa_verdict_citation_test_support import attach_product_evidence
from yoke_core.domain.qa_artifact_recording import handle_qa_artifact_add


@pytest.fixture
def walking(test_db, tmp_path, monkeypatch):
    mission.configure_test_machine(test_db, tmp_path, monkeypatch)
    item_id = 4596
    requirement_id = mission._materialize_mission(test_db, item_id=item_id)
    seed_registered_qa_launch(test_db, mission.ACTOR.session_id, actor_id=int(mission.ACTOR.actor_id))
    execution = mission.begin_plan_execution(
        test_db,
        item_id=item_id,
        transition_id="reviewing-implementation",
        actor_id=mission.ACTOR.actor_id,
        session_id=mission.ACTOR.session_id,
    )
    execution_id = str(execution["id"])
    subject = dict(
        item_id=item_id,
        execution_id=execution_id,
        requirement_id=requirement_id,
        ordinal=0,
    )
    begun = mission.handle_plan_case_begin(
        mission._request("test_machine.plan_case.begin", **subject)
    )
    assert begun.primary_success, begun.error
    contract = begun.result_payload["execution"]
    mission.register_host_control_factory(lambda _: mission.FakeHostControl())
    try:
        prepared = mission.prepare_agent_mission_contract(contract)
    finally:
        mission.clear_host_control_factory()
    ready = mission.handle_agent_mission_ready(
        mission._request("test_machine.mission.ready", **subject, payload=prepared)
    )
    assert ready.primary_success, ready.error
    current = mission.lock_plan_execution(test_db, execution_id)
    mission.begin_plan_review(test_db, current)
    return (
        execution_id,
        requirement_id,
        ready.result_payload["result"]["run_id"],
        contract,
    )


def _restore(requirement_id, run_id, content, *, actor=mission.ACTOR):
    outcome = handle_qa_artifact_add(
        FunctionCallRequest(
            function="qa.artifact.add",
            actor=actor,
            target=TargetRef(kind="qa_requirement", qa_requirement_id=requirement_id),
            payload={
                "run_id": run_id,
                "artifact_type": "starting_state_restore",
                "filename": "starting-state-restore.json",
                "content_type": "application/json",
                "content_base64": base64.b64encode(
                    json.dumps(content).encode()
                ).decode(),
            },
        )
    )
    assert outcome.primary_success, outcome.error
    return outcome.result_payload["qa_artifact_id"]


FAILED = {
    "baseline": "fresh-host",
    "restored": False,
    "ok": False,
    "error_code": "restore_failed",
}
VERIFIED = {"baseline": "fresh-host", "restored": True, "ok": True, "error_code": None}


def test_verified_retry_on_same_artifact_handle_leaves_no_reset_for_review_release(
    test_db, walking
):
    execution_id, requirement_id, run_id, contract = walking
    machine = contract["settings"]["resource_name"]
    lease_id = contract["lease_id"]

    artifact_id = _restore(requirement_id, run_id, FAILED)
    assert reset_owed(test_db, machine) == "fresh-host"
    for invalid in (
        {"restored": True},
        {**VERIFIED, "ok": False},
        {**VERIFIED, "baseline": "shell-preconfigured"},
    ):
        _restore(requirement_id, run_id, invalid)
        assert reset_owed(test_db, machine) == "fresh-host"
    _restore(
        requirement_id,
        run_id,
        VERIFIED,
        actor=ActorContext(actor_id="9", session_id="reviewer"),
    )
    assert reset_owed(test_db, machine) == "fresh-host"

    execution = mission.lock_plan_execution(test_db, execution_id)
    assert execution["state"] == "awaiting_walk_review"
    test_db.commit()
    assert _restore(requirement_id, run_id, VERIFIED) == artifact_id
    reset = recorded_test_machine_operation(
        test_db,
        test_machine=machine,
        operation="reset",
        lease_id=lease_id,
        contract_digest=contract["contract_digest"],
    )
    assert reset["status"] == "verified"
    assert reset["checks"] == [{"name": "fresh-host", "ok": True}]
    assert reset_owed(test_db, machine) is None

    evidence_id = attach_product_evidence(mission.ACTOR, requirement_id, run_id)
    execution = mission.lock_plan_execution(test_db, execution_id)
    bundle = mission.begin_plan_review(test_db, execution)
    with collect_released_hosts() as released:
        result = mission.submit_plan_review(
            test_db,
            execution,
            bundle_id=bundle["bundle_id"],
            bundle_digest=bundle["bundle_digest"],
            verdicts=[
                {
                    "requirement_id": requirement_id,
                    "verdict": "pass",
                    "rationale": (
                        f"Restoration verified in artifact {artifact_id}; "
                        f"the walk is shown in artifact {evidence_id}."
                    ),
                }
            ],
            reviewer_actor_id=mission.ACTOR.actor_id,
            reviewer_session_id=mission.ACTOR.session_id,
        )
    assert result["state"] == "passed"
    assert not mission.get_claim(test_db, lease_id).is_active
    assert released == {machine}
    assert released_reset_debts(released) == []


@pytest.mark.parametrize("same_contract", [False, True])
def test_replayed_restore_cannot_clear_newer_debt_on_same_lease(
    test_db, walking, same_contract
):
    _, requirement_id, run_id, contract = walking
    machine = contract["settings"]["resource_name"]
    lease_id = contract["lease_id"]
    digest = contract["contract_digest"] if same_contract else "d" * 64
    artifact_id = _restore(requirement_id, run_id, FAILED)
    assert _restore(requirement_id, run_id, VERIFIED) == artifact_id
    assert reset_owed(test_db, machine) is None

    new_debt = record_reset_owed(
        test_db,
        case={"host_baseline": "fresh-host"},
        test_machine=machine,
        lease_id=lease_id,
        contract_digest=digest,
    )
    test_db.commit()
    assert mission.get_claim(test_db, lease_id).is_active
    for replay in (FAILED, VERIFIED):
        assert _restore(requirement_id, run_id, replay) == artifact_id
        assert reset_owed(test_db, machine) == "fresh-host"
        assert (
            recorded_test_machine_operation(
                test_db,
                test_machine=machine,
                operation=RESET_OWED_OPERATION,
                lease_id=lease_id,
                contract_digest=digest,
            )
            == new_debt
        )
