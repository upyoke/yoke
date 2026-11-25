"""A mission review reads the evidence its walker attached after preparation."""

from __future__ import annotations

import base64
from typing import Any

import pytest

from runtime.api.domain import qa_execution_walk_states_test_support as walk_states
from runtime.api.domain.machine_qa_session_seed import seed_registered_qa_launch
from runtime.api.domain.agent_mission_qa_test_support import (
    ACTOR,
    FakeHostControl,
    _materialize_mission,
    _request,
    begin_plan_execution,
    begin_plan_review,
    clear_host_control_factory,
    configure_test_machine,
    handle_agent_mission_ready,
    handle_plan_case_begin,
    lock_plan_execution,
    prepare_agent_mission_contract,
    register_host_control_factory,
)
from yoke_contracts.api.function_call import FunctionCallRequest, TargetRef
from yoke_core.domain.qa_artifact_recording import handle_qa_artifact_add
from yoke_core.domain.qa_capture_agreement import AGENT_MISSION_DOCKET_REASON
from yoke_core.domain.qa_plan_execution_reconcile import _valid_capture


def _prepared_mission(test_db: Any, tmp_path: Any, monkeypatch: Any, item_id: int):
    configure_test_machine(test_db, tmp_path, monkeypatch)
    seed_registered_qa_launch(test_db, ACTOR.session_id)
    requirement_id = _materialize_mission(test_db, item_id=item_id)
    execution_id = str(
        begin_plan_execution(
            test_db,
            item_id=item_id,
            transition_id="reviewing-implementation",
            actor_id=ACTOR.actor_id,
            session_id=ACTOR.session_id,
        )["id"]
    )
    begun = handle_plan_case_begin(
        _request(
            "test_machine.plan_case.begin",
            item_id=item_id,
            execution_id=execution_id,
            ordinal=0,
            requirement_id=requirement_id,
        )
    )
    assert begun.primary_success, begun.error
    register_host_control_factory(lambda _material: FakeHostControl())
    try:
        prepared = prepare_agent_mission_contract(begun.result_payload["execution"])
    finally:
        clear_host_control_factory()
    ready = handle_agent_mission_ready(
        _request(
            "test_machine.mission.ready",
            item_id=item_id,
            execution_id=execution_id,
            ordinal=0,
            requirement_id=requirement_id,
            payload=prepared,
        )
    )
    assert ready.primary_success, ready.error
    run_id = int(ready.result_payload["result"]["run_id"])
    bundle = begin_plan_review(test_db, lock_plan_execution(test_db, execution_id))
    assert bundle["cases"][0]["artifacts"] == []
    assert bundle["cases"][0]["capture_degraded_reason"] == AGENT_MISSION_DOCKET_REASON
    return requirement_id, execution_id, run_id, bundle


def _attach(requirement_id: int, run_id: int, artifact_type: str) -> int:
    outcome = handle_qa_artifact_add(
        FunctionCallRequest(
            function="qa.artifact.add",
            actor=ACTOR,
            target=TargetRef(kind="qa_requirement", qa_requirement_id=requirement_id),
            payload={
                "run_id": run_id,
                "artifact_type": artifact_type,
                "content_type": "text/plain",
                "filename": f"{artifact_type}.txt",
                "content_base64": base64.b64encode(b"walker note").decode(),
            },
        )
    )
    assert outcome.primary_success, outcome.error
    return int(outcome.result_payload["qa_artifact_id"])


def test_review_begin_lists_evidence_attached_after_preparation(
    test_db: Any, tmp_path: Any, monkeypatch: Any
) -> None:
    requirement_id, execution_id, run_id, frozen = _prepared_mission(
        test_db, tmp_path, monkeypatch, 4590
    )
    evidence_id = _attach(requirement_id, run_id, "evidence")
    walk_states.record_handback(ACTOR, requirement_id, run_id)

    bundle = begin_plan_review(test_db, lock_plan_execution(test_db, execution_id))

    assert bundle["bundle_digest"] == frozen["bundle_digest"]
    case = bundle["cases"][0]
    assert case["capture_degraded_reason"] is None
    assert [a["artifact_type"] for a in case["artifacts"]] == [
        "evidence",
        "starting_state_restore",
    ]
    assert case["artifacts"][0]["id"] == evidence_id
    read = (
        f"yoke qa artifact read --requirement-id {requirement_id} "
        f"--artifact-id {evidence_id}"
    )
    assert case["artifacts"][0]["read_command"] == read
    assert read in bundle["dispatch"]["artifact_read_commands"]
    assert _valid_capture(test_db, bundle["bundle_id"]) is True


@pytest.mark.parametrize("artifact_type", [None, "diagnostic"])
def test_setup_only_mission_keeps_its_docket_reason(
    test_db: Any, tmp_path: Any, monkeypatch: Any, artifact_type: str | None
) -> None:
    item_id = 4591 if artifact_type is None else 4592
    requirement_id, execution_id, run_id, _ = _prepared_mission(
        test_db, tmp_path, monkeypatch, item_id
    )
    if artifact_type is not None:
        _attach(requirement_id, run_id, artifact_type)
    walk_states.record_handback(ACTOR, requirement_id, run_id)

    bundle = begin_plan_review(test_db, lock_plan_execution(test_db, execution_id))

    case = bundle["cases"][0]
    assert case["capture_degraded_reason"] == AGENT_MISSION_DOCKET_REASON
    assert "starting_state_restore" in [a["artifact_type"] for a in case["artifacts"]]
    assert _valid_capture(test_db, bundle["bundle_id"]) is False
