"""Missions recorded before an execution stops are judged from their evidence."""

from __future__ import annotations

from runtime.api.domain.qa_aborted_mission_review_test_support import (
    _recorded_mission as _recorded_mission,
)


from typing import Any

import pytest

from runtime.api.domain.agent_mission_qa_test_support import (
    ACTOR,
    _request,
)
from yoke_contracts.api.function_call import FunctionCallRequest, TargetRef
from yoke_core.domain.agent_mission_recording import (
    handle_agent_mission_access,
)
from yoke_core.domain.handlers.qa_plan_review import (
    handle_plan_review_begin,
    handle_plan_review_submit,
)
from yoke_core.domain.qa_plan_execution_lifecycle import finish_plan_execution
from yoke_core.domain.qa_plan_execution_state import (
    lock_plan_execution,
)


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
