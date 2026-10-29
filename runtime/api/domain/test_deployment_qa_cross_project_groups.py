"""Default plans stay owed across project boundaries; duplicate names refuse."""

import pytest

from runtime.api.domain.test_deployment_qa_cross_project_members import _ready, RUN, MEMBER
from runtime.api.domain.test_deployment_qa_stage_execution import _complete_case
from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain.deployment_qa_plan_group_writes import ensure_groups, resolve_group_subject
from yoke_core.domain.deployment_qa_plan_groups import run_groups
from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases
from yoke_core.domain.qa_plan_execution_state import begin_plan_execution


def _default(conn):
    _ready(conn, own_qa=True)
    conn.execute("UPDATE items SET workflow_id='issue',workflow_version_id="
                 "(SELECT current_version_id FROM workflows WHERE id='issue') WHERE id=%s", (MEMBER,))
    plan = create_plan(conn, project="carried", slug="release-smoke", target_environment="stage")
    replace_plan_cases(conn, plan_id=plan["id"], cases=[{
        "case_key": "command-smoke", "method_id": "command",
        "instructions": "Run the carried project smoke command.",
        "expected_outcome": "The command passes.", "method_config": {"command": "true"},
    }])
    conn.execute("INSERT INTO qa_plan_project_defaults(project_id,workflow_id,transition_id,"
                 "plan_id,qa_phase,attached_at) VALUES (995,'issue','release',%s,'post_deploy',now())", (plan["id"],))
    conn.commit()
    return plan["id"]


def test_cross_project_default_forms_and_runs_its_group(test_db):
    plan = _default(test_db)
    assert ensure_groups(test_db, RUN, "item-qa")
    test_db.commit()
    (group,) = run_groups(test_db, RUN)
    assert group.plan_id == plan
    execution = begin_plan_execution(test_db, deployment_run_id=RUN,
        deployment_stage="item-qa", plan=str(plan), actor_id="2", session_id="carried-qa")
    _complete_case(test_db, execution)
    (group,) = run_groups(test_db, RUN)
    assert group.closed and group.covered_item_ids == (MEMBER,)


def test_duplicate_plan_name_in_run_requires_exact_id(test_db):
    from yoke_core.domain.deployment_requirement_snapshots import snapshot_member_requirements, requirement_selection
    from runtime.api.domain.test_deployment_qa_plan_groups import _attach

    carried = _default(test_db)
    own = test_db.execute("SELECT id FROM qa_plans WHERE project_id=1 AND slug='release-smoke'").fetchone()[0]
    member = 9984
    insert_item(test_db, id=member, project_sequence=member, workflow_id="issue", status="done")
    test_db.execute("INSERT INTO deployment_run_items(run_id,item_id,added_at,requirement_snapshot) "
        "VALUES (%s,%s,now(),%s)", (RUN, member, snapshot_member_requirements(test_db,
            run_id=RUN, item_id=member, selection_json=requirement_selection())))
    _attach(test_db, member, own)
    ensure_groups(test_db, RUN, "item-qa")
    test_db.commit()
    with pytest.raises(ValueError, match="plan_group_ambiguous") as refusal:
        resolve_group_subject(test_db, RUN, "item-qa", "release-smoke", require_active=True)
    assert str(carried) in str(refusal.value) and str(own) in str(refusal.value)
