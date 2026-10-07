"""Plan-owned release obligations retain grouped baselines and member scope.

Only a machine-run case fans out across host baselines, so the grouped case
here is a host-control machine-state check.
"""

import json

import pytest

from runtime.api.domain.test_deployment_qa_admission_execution import (
    _original_requirement,
    _seed_selected_requirement_run,
)
from runtime.api.domain.test_deployment_qa_stage_execution import _plan
from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.deployment_requirement_snapshots import (
    _plan_snapshot,
    requirement_selection,
    snapshot_member_requirements,
)
from yoke_core.domain.qa_plan_management import QaPlanError, replace_plan_cases

STAGE = "member-qa"


@pytest.mark.parametrize("selection", ["attached", "frozen", "beside-flow-plan"])
def test_plan_owned_grouped_requirement_materializes_ordered_plan_once(
    test_db, selection
) -> None:
    item_id, other_item_id = 9820, 9821
    run_id = "run-grouped-member-plans"
    for member in (item_id, other_item_id):
        insert_item(
            test_db,
            id=member,
            project_sequence=member,
            workflow_id="issue",
            status="done",
        )
    plan_id = _plan(test_db, "grouped-member-plan")
    replace_plan_cases(
        test_db,
        plan_id=plan_id,
        cases=[
            {
                "case_key": "grouped-inspection",
                "position": 1,
                "method_id": "machine-state-check",
                "instructions": "Inspect the deployed release on both hosts.",
                "expected_outcome": "The deployed release is visible.",
                "method_config": {"assertions": [{"argv": ["/usr/bin/true"]}]},
                "host_baselines": ["shell-preconfigured", "fresh-host"],
            },
            {
                "case_key": "follow-up",
                "position": 2,
                "method_id": "command",
                "instructions": "Run the follow-up.",
                "expected_outcome": "The command passes.",
                "method_config": {"command": "true"},
            },
        ],
    )
    test_db.execute(
        "INSERT INTO qa_plan_item_attachments"
        "(item_id,plan_id,transition_id,qa_phase,attached_at) "
        "VALUES (%s,%s,'release','post_deploy',%s)",
        (item_id, plan_id, "2026-09-14T00:00:00Z"),
    )
    source_id = _original_requirement(
        test_db, item_id=item_id, method_id="machine-state-check"
    )
    test_db.execute(
        "UPDATE qa_requirements SET qa_kind='plan_case',plan_id=%s,"
        "plan_case_key='grouped-inspection',case_position=1,baseline_position=1,"
        "host_baseline='shell-preconfigured',starting_state='baseline' "
        "WHERE id=%s",
        (plan_id, source_id),
    )
    _seed_selected_requirement_run(
        test_db, run_id=run_id, item_id=item_id, requirement_id=source_id
    )
    if selection == "frozen":
        snapshot = snapshot_member_requirements(
            test_db,
            run_id=run_id,
            item_id=item_id,
            selection_json=requirement_selection(
                requirement_ids=(source_id,),
                plan_ids=(plan_id,),
            ),
        )
        test_db.execute(
            "UPDATE deployment_run_items SET requirement_snapshot=%s "
            "WHERE run_id=%s AND item_id=%s",
            (snapshot, run_id, item_id),
        )
    extra_plan_id = None
    if selection == "beside-flow-plan":
        extra_plan_id = _plan(test_db, "flow-plan")
        snapshot = {
            "schema": 1,
            "flow_id": f"flow-{run_id}",
            "selections": [
                {
                    "stage": STAGE,
                    **_plan_snapshot(test_db, extra_plan_id, project_id=1),
                }
            ],
        }
        test_db.execute(
            "UPDATE deployment_runs SET requirement_snapshot=%s WHERE id=%s",
            (json.dumps(snapshot), run_id),
        )
    other_source = _original_requirement(
        test_db, item_id=other_item_id, method_id="browser-inspection"
    )
    other_snapshot = snapshot_member_requirements(
        test_db,
        run_id=run_id,
        item_id=other_item_id,
        selection_json=requirement_selection(requirement_ids=(other_source,)),
    )
    test_db.execute(
        "INSERT INTO deployment_run_items(run_id,item_id,added_at,requirement_snapshot) "
        "VALUES (%s,%s,%s,%s)",
        (run_id, other_item_id, "2026-09-14T00:00:00Z", other_snapshot),
    )
    result = materialize_deployment_qa_stage(
        test_db,
        deployment_run_id=run_id,
        deployment_stage=STAGE,
        deployment_member_item_id=item_id,
    )
    rows = test_db.execute(
        "SELECT plan_id,plan_case_key,host_baseline,case_position,baseline_position "
        "FROM qa_requirements WHERE deployment_run_id=%s "
        "AND deployment_member_item_id=%s AND plan_id=%s "
        "ORDER BY case_position,baseline_position",
        (run_id, item_id, plan_id),
    ).fetchall()
    assert [tuple(row.values()) for row in rows] == [
        (plan_id, "grouped-inspection", "shell-preconfigured", 1, 1),
        (plan_id, "grouped-inspection", "fresh-host", 1, 2),
        (plan_id, "follow-up", None, 2, 1),
    ]
    assert len(result["created_requirement_ids"]) == 3 + (extra_plan_id is not None)
    again = materialize_deployment_qa_stage(
        test_db,
        deployment_run_id=run_id,
        deployment_stage=STAGE,
        deployment_member_item_id=item_id,
    )
    assert again["created_requirement_ids"] == []
    assert set(again["existing_requirement_ids"]) == set(
        result["created_requirement_ids"]
    )
    other = materialize_deployment_qa_stage(
        test_db,
        deployment_run_id=run_id,
        deployment_stage=STAGE,
        deployment_member_item_id=other_item_id,
    )
    other_rows = test_db.execute(
        "SELECT plan_id,host_baseline FROM qa_requirements "
        "WHERE id=ANY(%s) ORDER BY id",
        (other["created_requirement_ids"],),
    ).fetchall()
    assert [(row["plan_id"], row["host_baseline"]) for row in other_rows] == (
        [(None, None)]
        if extra_plan_id is None
        else [(None, None), (extra_plan_id, None)]
    )


def test_planless_grouped_requirement_still_refuses(test_db) -> None:
    item_id = 9822
    insert_item(
        test_db,
        id=item_id,
        project_sequence=item_id,
        workflow_id="issue",
        status="done",
    )
    source_id = _original_requirement(
        test_db, item_id=item_id, method_id="browser-inspection"
    )
    test_db.execute(
        "UPDATE qa_requirements SET host_baseline='fresh-host' WHERE id=%s",
        (source_id,),
    )
    _seed_selected_requirement_run(
        test_db,
        run_id="run-planless-group",
        item_id=item_id,
        requirement_id=source_id,
    )
    with pytest.raises(
        QaPlanError, match="grouped host baseline; admit its attached plan"
    ):
        materialize_deployment_qa_stage(
            test_db,
            deployment_run_id="run-planless-group",
            deployment_stage=STAGE,
            deployment_member_item_id=item_id,
        )
