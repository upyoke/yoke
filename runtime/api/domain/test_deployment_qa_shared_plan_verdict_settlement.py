"""A recorded plan-group verdict settles its group, never the run."""

from unittest.mock import patch

from runtime.api.domain.test_deployment_qa_plan_groups import (
    MEMBERS,
    RUN,
    _begin,
    _seed,
)
from runtime.api.domain.test_deployment_qa_plan_group_execution import _fail_case
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import deployment_qa_stage_settlement
from yoke_core.domain.deployment_qa_plan_group_writes import ensure_groups
from yoke_core.domain.deployment_qa_plan_groups import run_groups
from yoke_core.domain.deployment_qa_run_acceptance import item_qa_acceptance_blockers
from yoke_core.domain.handlers import qa_browser_writes


def _request(function_id: str, requirement_id: int, payload: dict):
    return FunctionCallRequest(
        function=function_id,
        actor=ActorContext(actor_id="2", session_id="plan-group-qa"),
        target=TargetRef(kind="qa_requirement", qa_requirement_id=requirement_id),
        payload=payload,
    )


def _group_requirement(conn) -> int:
    _seed(conn)
    (requirement_id,) = ensure_groups(conn, RUN, "item-qa")
    conn.commit()
    return requirement_id


def _arrive_at_item_qa(conn):
    conn.execute(
        "UPDATE deployment_runs SET current_stage='item-qa' WHERE id=%s", (RUN,)
    )
    conn.commit()


def test_completing_a_group_case_records_the_verdict_and_credits_every_member(
    test_db,
):
    requirement_id = _group_requirement(test_db)
    _arrive_at_item_qa(test_db)
    # The walk finished on a failed case, so its group stays open.
    _fail_case(test_db, _begin(test_db))
    test_db.commit()
    assert not run_groups(test_db, [RUN], "item-qa")[0].closed
    settle_group = deployment_qa_stage_settlement.settle_plan_group
    settled = []

    def spy(conn, subject):
        settled.append(subject["shared_plan"]["group_id"])
        return settle_group(conn, subject)

    with (
        patch("yoke_core.domain.qa_events.emit_qa_run_event"),
        patch.object(deployment_qa_stage_settlement, "settle_plan_group", spy),
    ):
        started = qa_browser_writes.handle_qa_run_add(
            _request("qa.run.add", requirement_id, {"performed_by": "worktree_run"})
        )
        run_id = int(started.result_payload["qa_run_id"])
        test_db.execute(
            "INSERT INTO qa_artifacts(qa_run_id,artifact_type,content_type,"
            "artifact_handle,created_at) VALUES (%s,'log','application/json',"
            "'evidence://group-case',NOW())",
            (run_id,),
        )
        test_db.commit()
        completed = qa_browser_writes.handle_qa_run_complete(
            _request(
                "qa.run.complete", requirement_id, {"run_id": run_id, "verdict": "pass"}
            )
        )

    assert completed.primary_success, completed.error
    assert (
        test_db.execute(
            "SELECT verdict FROM qa_runs WHERE id=%s", (run_id,)
        ).fetchone()[0]
        == "pass"
    )
    (group,) = run_groups(test_db, [RUN], "item-qa")
    assert settled == [group.group_id]
    assert group.covered_item_ids == tuple(MEMBERS)
    for member in MEMBERS:
        assert item_qa_acceptance_blockers(test_db, run_id=RUN, item_id=member) == []


def test_unsettleable_verdict_is_refused_by_name_and_not_recorded(test_db):
    requirement_id = _group_requirement(test_db)
    _arrive_at_item_qa(test_db)
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
                "qa.run.complete", requirement_id, {"run_id": run_id, "verdict": "pass"}
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


def test_persisted_verdict_refusal_names_environment_and_run():
    from unittest.mock import Mock
    import pytest
    from yoke_core.domain.qa_run_execution_evidence import (
        VerdictSettlementRefused, commit_settled_verdict,
    )

    with (
        patch("yoke_core.domain.qa_run_execution_evidence._settle_recorded_verdict",
              side_effect=ValueError("stage interrupted")),
        patch("yoke_core.domain.qa_run_execution_evidence.query_one",
              return_value={"verdict": "pass", "deployment_run_id": RUN}),
        pytest.raises(VerdictSettlementRefused) as refused,
    ):
        commit_settled_verdict(Mock(), 42)
    assert f"yoke --env CONTROL-PLANE watch deploy -- {RUN}" in str(refused.value)
    assert "The verdict is recorded" in str(refused.value)
