"""Ordinary failed restoration records debt before a later release can reuse a host."""

import base64
import json

import pytest

from runtime.api.domain import test_agent_mission_cleanup as cleanup_support
from runtime.api.domain.machine_operation_test_support import MACHINE
from runtime.api.domain.machine_qa_fixture_lifecycle_test_support import case_contract
from runtime.api.domain.machine_qa_host_test_support import configure_test_machine
from yoke_contracts.api.function_call import ActorContext, TargetRef
from yoke_core.domain.handlers.qa_artifact_add import handle_qa_artifact_add
from yoke_core.domain.machine_reset_debt import reset_owed
from yoke_core.domain import machine_qa_submission_recording as recording

removed_mission = cleanup_support.removed_mission


@pytest.mark.parametrize("restored", [False, True])
@pytest.mark.parametrize("owner", [False, True])
def test_current_mission_restore_records_debt_only_from_its_holder(
    test_db, removed_mission, restored, owner
):
    request, _, original = removed_mission
    restore = {"restored": restored, "baseline": "fresh-host"}
    request = request.model_copy(
        update={
            "target": TargetRef(
                kind="qa_requirement",
                qa_requirement_id=request.payload["requirement_id"],
            ),
            "payload": {
                "run_id": request.payload["run_id"],
                "artifact_type": "starting_state_restore",
                "filename": "restore.json",
                "content_type": "application/json",
                "content_base64": base64.b64encode(
                    json.dumps(restore).encode()
                ).decode(),
            },
            **(
                {}
                if owner
                else {"actor": ActorContext(actor_id="9", session_id="reviewer")}
            ),
        }
    )
    outcome = handle_qa_artifact_add(request)
    assert outcome.primary_success, outcome.error
    assert reset_owed(test_db, original["settings"]["resource_name"]) == (
        "fresh-host" if owner and not restored else None
    )


@pytest.mark.parametrize(
    "baseline,restored,error,ends_chain,owed",
    [
        ("fresh-host", False, None, True, "fresh-host"),
        ("fresh-host", True, None, True, None),
        (None, False, None, True, None),
        (None, False, "restore_failed", True, None),
        ("fresh-host", None, None, True, "fresh-host"),
        (None, None, None, True, None),
        ("fresh-host", None, None, False, None),
    ],
)
def test_case_capture_persists_unproven_restore_debt(
    test_db, tmp_path, monkeypatch, baseline, restored, error, ends_chain, owed
):
    configure_test_machine(test_db, tmp_path, monkeypatch)
    case = (
        case_contract(host_baseline=baseline)
        .model_copy(update={"ends_chain": ends_chain})
        .model_dump(mode="json")
    )
    restore = {"restored": restored, "baseline": baseline}
    if error:
        restore["error_code"] = error
    elif baseline is None:
        restore["reason"] = "the chain started as found"
    result = recording.MachineCaseSubmissionResult(
        requirement_id=case["requirement_id"],
        case_outcome="passed",
        verdict="pass",
        error_code=None,
        duration_ms=1,
        evidence={
            "runner_id": "host_control",
            "test_machine": MACHINE,
            "baseline": baseline,
            "method_id": case["method_id"],
            **({"starting_state_restore": restore} if restored is not None else {}),
        },
    )
    monkeypatch.setattr(
        recording, "record_machine_case_result", lambda *a, **kw: {"run_id": 17}
    )
    recorded = recording.record_submitted_case(
        test_db,
        case=case,
        result=result,
        resource_name=MACHINE,
        artifact_root=tmp_path,
        lease_id=77,
        contract_digest="d" * 64,
        artifact_rollback=recording.MachineQaArtifactRollback(),
    )
    assert recorded == {"run_id": 17}
    assert reset_owed(test_db, MACHINE) == owed
    assert result.evidence.get("starting_state_restore") == (
        restore if restored is not None else None
    )


def test_mission_replay_uses_accepted_contract_after_reset_and_new_debt(
    test_db, tmp_path, monkeypatch
):
    from runtime.api.domain.machine_qa_test_support import FakeHostControl
    from runtime.api.domain.test_agent_mission_qa import (
        ACTOR,
        _materialize_mission,
        _request,
    )
    from yoke_core.domain.agent_mission_recording import handle_agent_mission_ready
    from yoke_core.domain.handlers.machine_qa_plan_case import handle_plan_case_begin
    from yoke_core.domain.host_control_runner import (
        clear_host_control_factory,
        register_host_control_factory,
    )
    from yoke_core.domain.machine_qa_local_execution import (
        prepare_agent_mission_contract,
    )
    from yoke_core.domain.machine_reset_debt import record_reset_owed
    from yoke_core.domain.qa_plan_execution_state import begin_plan_execution

    configure_test_machine(test_db, tmp_path, monkeypatch)
    item_id = 7891
    requirement = _materialize_mission(test_db, item_id=item_id)
    record_reset_owed(
        test_db,
        case={"project_id": 1, "host_baseline": "shell-preconfigured"},
        test_machine=MACHINE,
        lease_id=77,
    )
    test_db.commit()
    execution = begin_plan_execution(
        test_db,
        item_id=item_id,
        transition_id="reviewing-implementation",
        actor_id=ACTOR.actor_id,
        session_id=ACTOR.session_id,
    )
    request = _request(
        "test_machine.plan_case.begin",
        item_id=item_id,
        execution_id=str(execution["id"]),
        requirement_id=requirement,
        ordinal=0,
    )
    begun = handle_plan_case_begin(request)
    assert begun.primary_success, begun.error
    original = begun.result_payload["execution"]
    assert original["reset_owed_baseline"] == "shell-preconfigured"
    control = FakeHostControl()
    register_host_control_factory(lambda _material: control)
    try:
        prepared = prepare_agent_mission_contract(original)
    finally:
        clear_host_control_factory()
    request = request.model_copy(
        update={
            "function": "test_machine.mission.ready",
            "payload": {**request.payload, **prepared},
        }
    )
    ready = handle_agent_mission_ready(request)
    assert ready.primary_success, ready.error
    assert reset_owed(test_db, MACHINE) is None
    replayed = handle_agent_mission_ready(request)
    assert replayed.primary_success, replayed.error
    assert replayed.result_payload == ready.result_payload
    run_id = ready.result_payload["result"]["run_id"]
    artifact = handle_qa_artifact_add(
        request.model_copy(
            update={
                "function": "qa.artifact.add",
                "target": TargetRef(
                    kind="qa_requirement", qa_requirement_id=requirement
                ),
                "payload": {
                    "run_id": run_id,
                    "artifact_type": "starting_state_restore",
                    "filename": "failed-restore.json",
                    "content_type": "application/json",
                    "content_base64": base64.b64encode(
                        json.dumps(
                            {"restored": False, "baseline": "fresh-host"}
                        ).encode()
                    ).decode(),
                },
            }
        )
    )
    assert artifact.primary_success, artifact.error
    assert reset_owed(test_db, MACHINE) == "fresh-host"
    replayed = handle_agent_mission_ready(request)
    assert replayed.primary_success, replayed.error
    assert replayed.result_payload == ready.result_payload
    assert reset_owed(test_db, MACHINE) == "fresh-host"


def test_failed_owed_reset_keeps_original_debt_without_starting_case(
    test_db, tmp_path, monkeypatch
):
    from yoke_core.domain.machine_reset_debt import record_reset_owed

    configure_test_machine(test_db, tmp_path, monkeypatch)
    case = case_contract(host_baseline="fresh-host").model_dump(mode="json")
    record_reset_owed(
        test_db,
        case={**case, "host_baseline": "shell-preconfigured"},
        test_machine=MACHINE,
        lease_id=77,
    )
    result = recording.MachineCaseSubmissionResult(
        requirement_id=case["requirement_id"],
        case_outcome="blocked_on_precondition",
        verdict="blocked",
        error_code="machine_needs_repair",
        duration_ms=1,
        evidence={
            "runner_id": "host_control",
            "test_machine": MACHINE,
            "baseline": "fresh-host",
            "method_id": case["method_id"],
            "case_started": False,
        },
    )
    monkeypatch.setattr(
        recording, "record_machine_case_result", lambda *a, **kw: {"run_id": 17}
    )
    recording.record_submitted_case(
        test_db,
        case={**case, "ends_chain": True},
        result=result,
        resource_name=MACHINE,
        artifact_root=tmp_path,
        lease_id=77,
        contract_digest="d" * 64,
        artifact_rollback=recording.MachineQaArtifactRollback(),
    )
    assert reset_owed(test_db, MACHINE) == "shell-preconfigured"
