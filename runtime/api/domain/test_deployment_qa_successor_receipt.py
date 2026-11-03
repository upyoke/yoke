"""Fresh successor work uses its receipt while inherited evidence stays valid."""

import json

import pytest

from runtime.api.domain import test_deployment_run_target_takeover as takeover
from runtime.api.domain.test_deployment_qa_takeover_identity import _execution
from runtime.api.fixtures.deployment_scoped_qa_run_fixture import record_case_verdict
from yoke_core.domain.deployment_qa_execution_target import (
    deployment_qa_execution_target,
    validate_deployment_execution_target,
)
from yoke_core.domain.deployment_qa_stage_contract import deployment_qa_stage_subject
from yoke_core.domain.qa_plan_execution_begin import begin_plan_execution
from yoke_core.domain.qa_plan_execution_lifecycle import finish_plan_execution
from yoke_core.domain.qa_plan_rematerialize_deployment import (
    rematerialize_for_deployment_stage,
)
from yoke_core.domain.qa_plan_rematerialize_deployment_subject import _pinned_target


def _arrive(conn, *, ready):
    conn.execute(
        "UPDATE deployment_runs n SET status='executing',current_stage=%s,"
        "composition_frozen_at=now(),requirement_snapshot=o.requirement_snapshot "
        "FROM deployment_runs o WHERE n.id=%s AND o.id=%s",
        (takeover.RUN_QA_STAGE, takeover.NEW, takeover.OLD),
    )
    if ready:
        from yoke_core.domain.deployment_stage_receipts import (
            allocate_deployment_stage_receipt,
            complete_deployment_stage_receipt,
        )

        receipt = allocate_deployment_stage_receipt(
            conn,
            run_id=takeover.NEW,
            stage_name="deploy",
            correlation_id="successor-deploy",
            target_kind="persistent_environment",
            executor="test",
            commit=False,
        )
        complete_deployment_stage_receipt(
            conn,
            run_id=takeover.NEW,
            receipt_id=receipt["id"],
            correlation_id=receipt["correlation_id"],
            status="ready",
            target_name="stage",
            observed_url="https://preview.example.test",
            observed_release_lineage=takeover.NEW_LINEAGE,
            executor_receipt="test://successor",
            commit=False,
        )
    conn.commit()


@pytest.mark.parametrize("ready", [False, True])
def test_successor_receipt_controls_fresh_target(test_db, monkeypatch, ready):
    execution = _execution(test_db, monkeypatch)
    _arrive(test_db, ready=ready)
    subject = deployment_qa_stage_subject(
        test_db,
        run_id=takeover.NEW,
        stage_name=takeover.RUN_QA_STAGE,
    )
    target = deployment_qa_execution_target(test_db, subject)
    assert target["deployment"]["run_id"] == (takeover.NEW if ready else takeover.OLD)
    assert target["observation"]["observed_release_lineage"] == (
        takeover.NEW_LINEAGE if ready else takeover.OLD_LINEAGE
    )
    validate_deployment_execution_target(test_db, execution)


def test_corrected_case_uses_successor_without_invalidating_prior_evidence(
    test_db,
    monkeypatch,
):
    execution = _execution(test_db, monkeypatch)
    requirement = execution["roster"][0]["requirement_id"]
    attempt = record_case_verdict(test_db, requirement, "fail", evidence=True)
    finish_plan_execution(
        test_db, execution, state="completed", reason="failed smoke recorded"
    )
    test_db.execute(
        "UPDATE qa_plan_cases SET instructions='run corrected smoke' WHERE plan_id="
        "(SELECT plan_id FROM qa_requirements WHERE id=%s)",
        (requirement,),
    )
    _arrive(test_db, ready=True)
    refreshed = rematerialize_for_deployment_stage(
        test_db,
        deployment_run_id=takeover.NEW,
        deployment_stage=takeover.RUN_QA_STAGE,
    )
    assert len(refreshed["created_requirement_ids"]) == 1
    new = begin_plan_execution(
        test_db,
        deployment_run_id=takeover.NEW,
        deployment_stage=takeover.RUN_QA_STAGE,
        actor_id="1",
        session_id=takeover.DRIVER_SESSION,
    )
    assert new["execution_target"]["deployment"]["run_id"] == takeover.NEW
    assert new["execution_target"]["observation"]["observed_release_lineage"] == (
        takeover.NEW_LINEAGE
    )
    assert new["execution_target_digest"] != execution["execution_target_digest"]
    validate_deployment_execution_target(test_db, execution)
    row = test_db.execute(
        "SELECT verdict FROM qa_runs WHERE id=%s",
        (attempt,),
    ).fetchone()
    assert row["verdict"] == "fail"
    # Mixed receipt history remains refreshable on subsequent reads.
    rematerialize_for_deployment_stage(
        test_db,
        deployment_run_id=takeover.NEW,
        deployment_stage=takeover.RUN_QA_STAGE,
    )


def test_materialized_history_selects_newest_receipt_independent_of_row_order():
    rows = [
        {
            "execution_target_json": json.dumps(
                {"observation": {"receipt_id": receipt}}
            ),
            "execution_target_digest": str(receipt),
        }
        for receipt in (20, 10)
    ]
    assert _pinned_target(rows, subject="run QA")["observation"]["receipt_id"] == 20
