"""A recorded shared-plan verdict settles its shared group, never the run."""

from unittest.mock import patch

from runtime.api.domain.test_deployment_qa_shared_plans import (
    MEMBERS,
    RUN,
    _begin,
    _materialize,
    _seed,
)
from runtime.api.domain.test_deployment_qa_stage_execution import _complete_case
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import deployment_qa_stage_settlement
from yoke_core.domain.deployment_qa_stage_gate import deployment_qa_stage_status
from yoke_core.domain.handlers import qa_browser_writes


def _request(function_id: str, requirement_id: int, payload: dict):
    return FunctionCallRequest(
        function=function_id,
        actor=ActorContext(actor_id="2", session_id="shared-qa"),
        target=TargetRef(kind="qa_requirement", qa_requirement_id=requirement_id),
        payload=payload,
    )


def test_completing_a_shared_case_records_the_verdict_and_credits_both_members(
    test_db,
):
    _seed(test_db)
    requirement_id = _materialize(test_db, MEMBERS[0])["created_requirement_ids"][0]
    assert _materialize(test_db, MEMBERS[1])["existing_requirement_ids"] == [
        requirement_id
    ]
    _complete_case(test_db, _begin(test_db, MEMBERS[0]))
    test_db.execute(
        "UPDATE deployment_runs SET current_stage='item-qa' WHERE id=%s", (RUN,)
    )
    test_db.commit()
    settle_acceptance = deployment_qa_stage_settlement.settle_acceptance
    credited = []

    def spy(conn, *, run_id, stage, member):
        credited.append(member)
        return settle_acceptance(conn, run_id=run_id, stage=stage, member=member)

    with (
        patch("yoke_core.domain.qa_events.emit_qa_run_event"),
        patch.object(deployment_qa_stage_settlement, "settle_acceptance", spy),
    ):
        started = qa_browser_writes.handle_qa_run_add(
            _request("qa.run.add", requirement_id, {"performed_by": "worktree_run"})
        )
        run_id = int(started.result_payload["qa_run_id"])
        test_db.execute(
            "INSERT INTO qa_artifacts(qa_run_id,artifact_type,content_type,"
            "artifact_handle,created_at) VALUES (%s,'log','application/json',"
            "'evidence://shared-case',NOW())",
            (run_id,),
        )
        test_db.commit()
        completed = qa_browser_writes.handle_qa_run_complete(
            _request(
                "qa.run.complete",
                requirement_id,
                {"run_id": run_id, "verdict": "pass"},
            )
        )

    assert completed.primary_success, completed.error
    assert (
        test_db.execute(
            "SELECT verdict FROM qa_runs WHERE id=%s", (run_id,)
        ).fetchone()[0]
        == "pass"
    )
    assert credited == list(MEMBERS)
    for member in MEMBERS:
        status = deployment_qa_stage_status(
            test_db, run_id=RUN, stage_name="item-qa", member_item_id=member
        )
        assert status["accepted"], status


def test_unsettleable_verdict_is_refused_by_name_and_not_recorded(test_db):
    _seed(test_db)
    requirement_id = _materialize(test_db, MEMBERS[0])["created_requirement_ids"][0]
    with patch("yoke_core.domain.qa_events.emit_qa_run_event"):
        started = qa_browser_writes.handle_qa_run_add(
            _request("qa.run.add", requirement_id, {"performed_by": "worktree_run"})
        )
    run_id = int(started.result_payload["qa_run_id"])
    with (
        patch("yoke_core.domain.qa_events.emit_qa_run_event"),
        patch(
            "yoke_core.domain.qa_run_execution_evidence._settle_recorded_verdict",
            side_effect=ValueError("stage subject unresolved"),
        ),
    ):
        refused = qa_browser_writes.handle_qa_run_complete(
            _request(
                "qa.run.complete",
                requirement_id,
                {"run_id": run_id, "verdict": "pass"},
            )
        )

    assert refused.error.code == "qa_verdict_settlement_refused"
    assert "stage subject unresolved" in refused.error.message
    assert "The verdict was not recorded" in refused.error.message
    assert (
        test_db.execute(
            "SELECT verdict FROM qa_runs WHERE id=%s", (run_id,)
        ).fetchone()[0]
        is None
    )
