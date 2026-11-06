"""Frozen member obligations and executor-selected deployment QA cases."""

from __future__ import annotations

from runtime.api.domain.deployment_qa_admission_execution_test_support import (
    _original_requirement as _original_requirement,
)


import json


from runtime.api.fixtures.completed_delivery import (
    _stage as _stage,
    seed_selected_requirement_run as _seed_selected_requirement_run,
)
from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.deployment_qa_admission_materialization import (
    admitted_requirement_case_key,
)
from yoke_core.domain.qa_plan_execution_roster import ordered_plan_requirements


def test_explicit_screenshot_obligation_materializes_before_execution(test_db) -> None:
    item_id = 9710
    insert_item(
        test_db, id=item_id, project_sequence=710, workflow_id="issue", status="done"
    )
    original_id = _original_requirement(
        test_db, item_id=item_id, method_id="browser-inspection"
    )
    _seed_selected_requirement_run(
        test_db,
        run_id="run-admitted-screenshot",
        item_id=item_id,
        requirement_id=original_id,
    )

    result = materialize_deployment_qa_stage(
        test_db,
        deployment_run_id="run-admitted-screenshot",
        deployment_stage="member-qa",
        deployment_member_item_id=item_id,
    )
    assert len(result["created_requirement_ids"]) == 1
    roster = ordered_plan_requirements(
        test_db,
        deployment_run_id="run-admitted-screenshot",
        deployment_stage="member-qa",
        deployment_member_item_id=item_id,
    )
    assert roster[0]["plan_id"] is None
    assert roster[0]["case_key"] == admitted_requirement_case_key(original_id)
    scoped = test_db.execute(
        "SELECT item_id,deployment_member_item_id,method_id,execution_target_json "
        "FROM qa_requirements WHERE id=%s",
        (roster[0]["requirement_id"],),
    ).fetchone()
    assert scoped["item_id"] is None and scoped["deployment_member_item_id"] == item_id
    target = json.loads(scoped["execution_target_json"])
    assert target["environment"]["name"] == "stage"
    assert target["deployment"]["release_lineage"] == "c" * 40
    assert (
        test_db.execute(
            "SELECT item_id FROM qa_requirements WHERE id=%s", (original_id,)
        ).fetchone()["item_id"]
        == item_id
    )
