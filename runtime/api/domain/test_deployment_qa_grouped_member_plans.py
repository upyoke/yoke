"""Plan-owned release obligations retain grouped baselines and member scope.

Only a machine-run case fans out across host baselines, so the grouped case
here is a host-control machine-state check. An attached plan runs as one
plan group of the run; each member materializes only its own item cases and
the flow's plan.
"""

import json

import pytest

from runtime.api.domain.test_deployment_qa_admission_execution import (
    _original_requirement,
    _seed_selected_requirement_run,
)
from runtime.api.domain.test_deployment_qa_stage_execution import _plan
from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain.deployment_qa_plan_group_writes import ensure_groups
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
RUN = "run-grouped-member-plans"


def _grouped_plan(conn) -> int:
    plan_id = _plan(conn, "grouped-member-plan")
    replace_plan_cases(
        conn,
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
    return plan_id


def _add_member(conn, item_id: int) -> None:
    source = _original_requirement(conn, item_id=item_id, method_id="browser-inspection")
    snapshot = snapshot_member_requirements(
        conn,
        run_id=RUN,
        item_id=item_id,
        selection_json=requirement_selection(requirement_ids=(source,)),
    )
    conn.execute(
        "INSERT INTO deployment_run_items(run_id,item_id,added_at,requirement_snapshot) "
        "VALUES (%s,%s,%s,%s)",
        (RUN, item_id, "2026-09-14T00:00:00Z", snapshot),
    )


def _member_rows(conn, result):
    return [
        (row["plan_id"], row["host_baseline"])
        for row in conn.execute(
            "SELECT plan_id,host_baseline FROM qa_requirements "
            "WHERE id=ANY(%s) ORDER BY id",
            (result["created_requirement_ids"],),
        ).fetchall()
    ]


@pytest.mark.parametrize("beside_flow_plan", [False, True])
def test_attached_grouped_plan_materializes_ordered_once_as_a_plan_group(
    test_db, beside_flow_plan
) -> None:
    item_id, other_item_id = 9820, 9821
    for member in (item_id, other_item_id):
        insert_item(
            test_db,
            id=member,
            project_sequence=member,
            workflow_id="issue",
            status="done",
        )
    plan_id = _grouped_plan(test_db)
    test_db.execute(
        "INSERT INTO qa_plan_item_attachments"
        "(item_id,plan_id,transition_id,qa_phase,attached_at) "
        "VALUES (%s,%s,'release','post_deploy',%s)",
        (item_id, plan_id, "2026-09-14T00:00:00Z"),
    )
    own = _original_requirement(test_db, item_id=item_id, method_id="browser-inspection")
    _seed_selected_requirement_run(
        test_db, run_id=RUN, item_id=item_id, requirement_id=own
    )
    extra_plan_id = None
    if beside_flow_plan:
        extra_plan_id = _plan(test_db, "flow-plan")
        snapshot = {
            "schema": 1,
            "flow_id": f"flow-{RUN}",
            "selections": [
                {"stage": STAGE, **_plan_snapshot(test_db, extra_plan_id, project_id=1)}
            ],
        }
        test_db.execute(
            "UPDATE deployment_runs SET requirement_snapshot=%s WHERE id=%s",
            (json.dumps(snapshot), RUN),
        )
    _add_member(test_db, other_item_id)
    test_db.commit()

    created = ensure_groups(test_db, RUN, STAGE)
    test_db.commit()

    rows = test_db.execute(
        "SELECT id,plan_case_key,host_baseline,case_position,baseline_position,"
        "deployment_member_item_id FROM qa_requirements WHERE deployment_run_id=%s "
        "AND plan_id=%s ORDER BY case_position,baseline_position",
        (RUN, plan_id),
    ).fetchall()
    assert [tuple(row.values())[1:] for row in rows] == [
        ("grouped-inspection", "shell-preconfigured", 1, 1, None),
        ("grouped-inspection", "fresh-host", 1, 2, None),
        ("follow-up", None, 2, 1, None),
    ]
    assert sorted(created) == sorted(row["id"] for row in rows)
    assert ensure_groups(test_db, RUN, STAGE) == []

    flow_rows = [] if extra_plan_id is None else [(extra_plan_id, None)]
    for member in (item_id, other_item_id):
        result = materialize_deployment_qa_stage(
            test_db,
            deployment_run_id=RUN,
            deployment_stage=STAGE,
            deployment_member_item_id=member,
        )
        assert _member_rows(test_db, result) == [(None, None), *flow_rows]
        again = materialize_deployment_qa_stage(
            test_db,
            deployment_run_id=RUN,
            deployment_stage=STAGE,
            deployment_member_item_id=member,
        )
        assert again["created_requirement_ids"] == []
        assert set(again["existing_requirement_ids"]) == set(
            result["created_requirement_ids"]
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
