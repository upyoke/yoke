"""Missions recorded before an execution stops are judged from their evidence."""

from __future__ import annotations

from typing import Any

import pytest

from runtime.api.domain.machine_qa_host_test_support import (
    configure_test_machine,
)
from runtime.api.domain.machine_qa_test_support import FakeHostControl
from runtime.api.domain.test_agent_mission_qa import (
    ACTOR,
    _materialize_mission,
    _request,
)
from yoke_contracts.api.function_call import FunctionCallRequest, TargetRef
from yoke_core.domain.agent_mission_recording import (
    handle_agent_mission_access,
    handle_agent_mission_ready,
)
from yoke_core.domain.handlers.machine_qa_plan_case import handle_plan_case_begin
from yoke_core.domain.handlers.qa_plan_review import (
    handle_plan_review_begin,
    handle_plan_review_submit,
)
from yoke_core.domain.host_control_runner import (
    clear_host_control_factory,
    register_host_control_factory,
)
from yoke_core.domain.machine_qa_local_execution import (
    prepare_agent_mission_contract,
)
from yoke_core.domain.qa_plan_execution_lifecycle import finish_plan_execution
from yoke_core.domain.qa_plan_execution_state import (
    begin_plan_execution,
    lock_plan_execution,
)


def _recorded_mission(test_db: Any, tmp_path: Any, monkeypatch: Any, item_id: int):
    configure_test_machine(test_db, tmp_path, monkeypatch)
    requirement_id = _materialize_mission(test_db, item_id=item_id)
    execution = begin_plan_execution(
        test_db,
        item_id=item_id,
        transition_id="reviewing-implementation",
        actor_id=ACTOR.actor_id,
        session_id=ACTOR.session_id,
    )
    execution_id = str(execution["id"])
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
    return requirement_id, execution_id, int(ready.result_payload["result"]["run_id"])


@pytest.mark.parametrize("state", ["aborted", "error"])
def test_recorded_mission_is_reviewed_from_evidence_after_the_walk_stops(
    test_db: Any, tmp_path: Any, monkeypatch: Any, state: str
) -> None:
    item_id = 4560 if state == "aborted" else 4561
    requirement_id, execution_id, run_id = _recorded_mission(
        test_db, tmp_path, monkeypatch, item_id
    )
    finish_plan_execution(
        test_db,
        lock_plan_execution(test_db, execution_id),
        state=state,
        reason="a later shared case stopped the walk",
    )
    test_db.commit()
    target = TargetRef(kind="item", item_id=item_id)
    begun = handle_plan_review_begin(
        FunctionCallRequest(
            function="qa.plan_review.begin",
            actor=ACTOR,
            target=target,
            payload={"execution_id": execution_id},
        )
    )
    assert begun.primary_success, begun.error
    bundle = begun.result_payload["review_bundle"]
    assert [case["capture_run_id"] for case in bundle["cases"]] == [run_id]
    dispatch = bundle["dispatch"]
    assert "walker_dispatches" not in dispatch
    assert dispatch["submit_command"]
    assert f"judge mission case(s) {requirement_id} only from" in dispatch["prompt"]

    refused = handle_agent_mission_access(
        _request(
            "test_machine.mission.access",
            item_id=item_id,
            execution_id=execution_id,
            requirement_id=requirement_id,
        )
    )
    assert refused.error is not None
    assert refused.error.code == "agent_mission_access_failed"
    assert "no walker can reach it" in refused.error.message
    assert "yoke qa plan review-begin" in refused.error.message

    rationale = "Only setup receipts were recorded; the mission was never walked."
    submitted = handle_plan_review_submit(
        FunctionCallRequest(
            function="qa.plan_review.submit",
            actor=ACTOR,
            target=target,
            payload={
                "execution_id": execution_id,
                "bundle_id": bundle["bundle_id"],
                "bundle_digest": bundle["bundle_digest"],
                "verdicts": [
                    {
                        "requirement_id": requirement_id,
                        "verdict": "fail",
                        "rationale": rationale,
                    }
                ],
            },
        )
    )
    assert submitted.primary_success, submitted.error
    assert submitted.result_payload["state"] == state
    final = test_db.execute(
        "SELECT verdict,verdict_reason FROM qa_runs WHERE id=%s", (run_id,)
    ).fetchone()
    assert tuple(final) == ("fail", rationale)
