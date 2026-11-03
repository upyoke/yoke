"""Pending review holds only the target it captured, including after takeover."""

import json

import pytest

from runtime.api.domain import test_deployment_run_target_takeover as takeover
from runtime.api.domain.test_deployment_qa_takeover_identity import _execution
from yoke_core.domain.deployment_qa_execution_target import (
    validate_deployment_execution_target,
)
from yoke_core.domain.deployment_stage_receipts import (
    allocate_deployment_stage_receipt,
    complete_deployment_stage_receipt,
)
from yoke_core.domain.qa_pending_agent_review import pending_review_requirements
from yoke_core.domain.qa_plan_execution_begin import begin_plan_execution
from yoke_core.domain.qa_plan_nothing_owed import QaPlanNothingOwed
from yoke_core.domain.qa_plan_rematerialize_deployment import (
    rematerialize_for_deployment_stage,
)
from yoke_core.domain.qa_plan_settled_review import open_unsettled_roster


@pytest.mark.parametrize("rematerialize", [False, True])
def test_takeover_pending_review_holds_only_its_frozen_target(
    test_db, monkeypatch, rematerialize
):
    execution = _execution(test_db, monkeypatch)
    requirement_id = execution["roster"][0]["requirement_id"]
    # Preserve a stopped capture's pending bundle under the successor owner.
    test_db.execute(
        "UPDATE qa_plan_executions SET state='aborted' WHERE id=%s",
        (execution["id"],),
    )
    test_db.execute(
        "INSERT INTO qa_plan_review_bundles "
        "(id,execution_id,roster_digest,bundle_digest,bundle_json,state,created_at) "
        "VALUES (%s,%s,%s,'captured',%s,'pending',CURRENT_TIMESTAMP)",
        (
            f"bundle-{execution['id']}",
            execution["id"],
            execution["roster_digest"],
            json.dumps({"cases": [{"requirement_id": requirement_id}]}),
        ),
    )
    test_db.commit()
    if rematerialize:
        receipt = allocate_deployment_stage_receipt(
            test_db,
            run_id=takeover.NEW,
            stage_name="deploy",
            correlation_id="successor-deploy",
            target_kind="persistent_environment",
            executor="test",
        )
        complete_deployment_stage_receipt(
            test_db,
            run_id=takeover.NEW,
            receipt_id=int(receipt["id"]),
            correlation_id="successor-deploy",
            status="ready",
            target_name="stage",
            observed_url="https://preview.example.test",
            observed_release_lineage=takeover.NEW_LINEAGE,
            executor_receipt="test://successor-deploy-ready",
        )
        test_db.execute(
            "UPDATE deployment_runs n SET status='executing',current_stage=%s,"
            "composition_frozen_at=now(),requirement_snapshot=o.requirement_snapshot "
            "FROM deployment_runs o WHERE n.id=%s AND o.id=%s",
            (takeover.RUN_QA_STAGE, takeover.NEW, takeover.OLD),
        )
        rematerialize_for_deployment_stage(
            test_db,
            deployment_run_id=takeover.NEW,
            deployment_stage=takeover.RUN_QA_STAGE,
        )

    def begin():
        return begin_plan_execution(
            test_db,
            deployment_run_id=takeover.NEW,
            deployment_stage=takeover.RUN_QA_STAGE,
            actor_id="1",
            session_id=takeover.DRIVER_SESSION,
        )

    if rematerialize:
        fresh = begin()
        assert fresh["id"] != execution["id"]
        assert fresh["execution_target"]["deployment"]["run_id"] == takeover.NEW
        assert fresh["execution_target_digest"] != execution["execution_target_digest"]
        assert fresh["roster"][0]["requirement_id"] == requirement_id
        with pytest.raises(ValueError, match="qa_execution_target_unowned") as refused:
            validate_deployment_execution_target(test_db, execution)
        assert (
            f"yoke qa plan reconcile --project yoke --execution-id {execution['id']} "
            '--reason "Reconcile QA frozen to a superseded target"'
        ) in str(refused.value)
    else:
        with pytest.raises(QaPlanNothingOwed, match="review-begin"):
            open_unsettled_roster(
                test_db,
                execution["roster"],
                item_id=None,
                transition_id=None,
                deployment_run_id=takeover.NEW,
                deployment_stage=takeover.RUN_QA_STAGE,
                deployment_member_item_id=None,
            )

    # Other readers still expose the old review and its evidence as history.
    pending = pending_review_requirements(test_db, [requirement_id], stopped_only=True)
    assert pending[requirement_id].execution_id == execution["id"]
    assert (
        pending[requirement_id].execution_target_digest
        == execution["execution_target_digest"]
    )
