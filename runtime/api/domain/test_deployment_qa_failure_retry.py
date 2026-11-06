"""Retrying a failed deployment continues its open QA and preserves manual retirements."""

import pytest

from runtime.api.domain.test_deployment_qa_stage_execution import (
    _plan,
    _seed_run,
    _stages,
)
from yoke_core.domain.deployment_qa_stage_gate import deployment_qa_stage_status
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.deployment_run_terminalization import terminalize_run_on
from yoke_core.domain.deployment_runs_crud_mutate import cmd_update
from yoke_core.domain.qa_plan_execution_state import begin_plan_execution
from yoke_core.domain.qa_plan_attachment_retract import retract_requirements


@pytest.mark.parametrize("manual_source", [None, "operator", "agent"])
def test_failed_run_retry_continues_its_live_qa_walk(test_db, monkeypatch, manual_source):
    run_id, item_id = "run-retry-retired-qa", 9754
    _seed_run(
        test_db,
        run_id=run_id,
        stages=_stages(_plan(test_db, "retry-retired-smoke")),
        members=(item_id,),
    )
    materialize_deployment_qa_stage(
        test_db,
        deployment_run_id=run_id,
        deployment_stage="item-qa",
        deployment_member_item_id=item_id,
    )
    before = begin_plan_execution(
        test_db,
        deployment_run_id=run_id,
        deployment_stage="item-qa",
        deployment_member_item_id=item_id,
        actor_id="2",
        session_id="retry-qa",
    )
    requirement_id = int(before["roster"][0]["requirement_id"])
    if manual_source:
        retract_requirements(
            test_db, [requirement_id], reason="case outside scope", source=manual_source
        )
    terminalize_run_on(
        test_db,
        run_id,
        disposition="failed",
        reason="environment failed",
        actor_id=None,
        session_id="driver",
    )
    test_db.commit()
    assert (test_db.execute(
        "SELECT retracted_at FROM qa_requirements WHERE id=%s", (requirement_id,)
    ).fetchone()[0] is not None) is bool(manual_source)
    # The fixture carries a synthetic revision; Git containment is separately
    # proven by the source-binding tests, not by this QA recovery check.
    monkeypatch.setattr(
        "yoke_core.domain.deployment_run_contained_items.record_attested_candidate_containment",
        lambda *args: None,
    )
    assert cmd_update(run_id, "status", "executing") is None
    materialize_deployment_qa_stage(
        test_db,
        deployment_run_id=run_id,
        deployment_stage="item-qa",
        deployment_member_item_id=item_id,
    )
    status = deployment_qa_stage_status(
        test_db,
        run_id=run_id,
        stage_name="item-qa",
        member_item_id=item_id,
        notify_acceptance=False,
    )
    if manual_source:
        assert status["accepted"]
        assert (
            test_db.execute(
                "SELECT retraction_source FROM qa_requirements WHERE id=%s",
                (requirement_id,),
            ).fetchone()[0]
            == manual_source
        )
        return
    assert not status["accepted"], "failure retirement must not discharge QA on retry"
    after = begin_plan_execution(
        test_db,
        deployment_run_id=run_id,
        deployment_stage="item-qa",
        deployment_member_item_id=item_id,
        actor_id="2",
        session_id="retry-qa",
    )
    assert after["id"] == before["id"]
    assert int(after["roster"][0]["requirement_id"]) == requirement_id
    assert (
        test_db.execute(
            "SELECT state FROM qa_plan_executions WHERE id=%s", (before["id"],)
        ).fetchone()[0]
        == "active"
    )
