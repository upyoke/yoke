"""Plan-case corrections retain the frozen run-preview environment label."""

import pytest

from runtime.api.domain.test_deployment_qa_multi_item_scoped_stages import (
    LINEAGE, PREVIEW_QA, _bind_plan, _environment_id, _point_run_at_environment,
    _preview_qa_stages, _seed_ephemeral_capability,
)
from runtime.api.fixtures.deployment_scoped_qa_run_fixture import record_case_verdict, seed_run_standing_on_qa_stage
from yoke_core.domain.deployment_qa_stage_materialization import materialize_deployment_qa_stage
from yoke_core.domain.qa_requirement_supersession import supersede_requirement
from yoke_core.domain.qa_requirement_waive_liveness import NOT_LIVE_CODE, RequirementNotLiveError, require_live_for_waiver


def test_plan_case_on_preview_stage_supersedes_the_failed_case(test_db):
    run_id = "run-preview-correction"
    _seed_ephemeral_capability(test_db)
    stages = _preview_qa_stages()
    stages[1]["scope"] = "run"
    seed_run_standing_on_qa_stage(test_db, run_id=run_id, project="yoke",
        stages=stages, members=(), lineage=LINEAGE, receipt_target_kind="run_preview")
    environment = _environment_id(test_db)
    _point_run_at_environment(test_db, run_id, environment)
    original = _bind_plan(test_db, slug="preview-original", environment_id=environment)
    scope = {"deployment_run_id": run_id, "deployment_stage": PREVIEW_QA}
    first = materialize_deployment_qa_stage(test_db, **scope, agent_plan=str(original))
    admitted = first["created_requirement_ids"][0]
    record_case_verdict(test_db, admitted, "fail", evidence=False)
    corrected_plan = _bind_plan(test_db, slug="preview-corrected", environment_id=environment)
    corrected = materialize_deployment_qa_stage(test_db, **scope,
        agent_plan=str(corrected_plan), replacement_keys={"command-smoke"})["created_requirement_ids"][0]
    labels = test_db.execute("SELECT target_env FROM qa_requirements WHERE id=ANY(%s)", ([admitted, corrected],)).fetchall()
    assert labels[0][0] and labels[0][0] == labels[1][0]
    record_case_verdict(test_db, corrected, "pass", evidence=True)
    receipt = supersede_requirement(test_db, requirement_id=admitted,
        superseded_by_requirement_id=corrected, rationale="the preview serves the corrected route")
    assert receipt["superseded_by_requirement_id"] == corrected
    with pytest.raises(RequirementNotLiveError) as refusal:
        require_live_for_waiver(test_db, admitted)
    assert NOT_LIVE_CODE in str(refusal.value)
    assert f"--requirement-id {corrected}" in str(refusal.value)
