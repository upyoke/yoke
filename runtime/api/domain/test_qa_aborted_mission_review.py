"""Missions recorded before an execution stops are judged from their evidence."""

from __future__ import annotations

import base64

from runtime.api.domain.qa_aborted_mission_review_test_support import (
    _recorded_mission as _recorded_mission,
)


from typing import Any

import pytest

from runtime.api.domain.agent_mission_qa_test_support import (
    ACTOR,
    _request,
)
from runtime.api.domain.qa_verdict_citation_test_support import cite_case

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
from yoke_core.domain.qa_artifact_recording import handle_qa_artifact_add


@pytest.mark.parametrize("state", ["aborted", "error"])
def test_recorded_mission_is_reviewed_from_evidence_after_the_walk_stops(
    test_db: Any, tmp_path: Any, monkeypatch: Any, state: str
) -> None:
    item_id = 4560 if state == "aborted" else 4561
    requirement_id, execution_id, run_id = _recorded_mission(
        test_db, tmp_path, monkeypatch, item_id
    )
    evidence = handle_qa_artifact_add(
        FunctionCallRequest(
            function="qa.artifact.add",
            actor=ACTOR,
            target=TargetRef(kind="qa_requirement", qa_requirement_id=requirement_id),
            payload={
                "run_id": run_id,
                "artifact_type": "evidence",
                "content_type": "text/plain",
                "filename": "mission-observation.txt",
                "content_base64": base64.b64encode(b"Expected terminal frame was absent").decode(),
            },
        )
    )
    assert evidence.primary_success, evidence.error
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
    assert evidence.result_payload["qa_artifact_id"] in [
        artifact["id"] for artifact in bundle["cases"][0]["artifacts"]
    ]
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

    rationale = cite_case(bundle, "The expected terminal frame was absent.")
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
