"""Environment applicability for frozen deployment QA obligations."""

from runtime.api.domain.test_deployment_qa_admission_execution import (
    _original_requirement,
    _seed_selected_requirement_run,
)
from runtime.api.domain.test_deployment_qa_stage_execution import _plan
from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)


def test_stage_only_requirement_is_not_applied_to_production(test_db) -> None:
    item_id = 9712
    insert_item(
        test_db,
        id=item_id,
        project_sequence=712,
        workflow_id="issue",
        status="done",
    )
    original_id = _original_requirement(
        test_db, item_id=item_id, method_id="browser-inspection"
    )
    plan_id = _plan(test_db, "production-agent-selection")
    _seed_selected_requirement_run(
        test_db,
        run_id="run-production-selection",
        item_id=item_id,
        requirement_id=original_id,
        environment="prod",
    )

    result = materialize_deployment_qa_stage(
        test_db,
        deployment_run_id="run-production-selection",
        deployment_stage="member-qa",
        deployment_member_item_id=item_id,
        agent_plan=str(plan_id),
    )

    assert len(result["created_requirement_ids"]) == 1
    scoped = test_db.execute(
        "SELECT plan_id,plan_case_key FROM qa_requirements "
        "WHERE deployment_run_id='run-production-selection'"
    ).fetchall()
    assert [(row["plan_id"], row["plan_case_key"]) for row in scoped] == [
        (plan_id, "command-smoke")
    ]
