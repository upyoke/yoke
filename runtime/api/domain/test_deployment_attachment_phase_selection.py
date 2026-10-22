"""Admission selects a plan attachment by its admitted QA boundary."""

import json

import pytest

from runtime.api.domain.test_deployment_qa_stage_execution import (
    _plan,
    _seed_run,
    _stages,
)
from runtime.api.fixtures.backlog_inserts import insert_qa_requirement
from runtime.api.fixtures.deployment_run_driver_fixture import release_seeded_driver
from yoke_core.domain.deployment_admission_reads import AdmissionReads
from yoke_core.domain.deployment_requirement_snapshots import (
    requirement_selection,
    snapshot_member_requirements,
)
from yoke_core.domain.deployment_qa_frozen_plan_selection import frozen_stage_plans
from yoke_core.domain.deployment_qa_stage_contract import deployment_qa_stage_subject
from yoke_core.domain.deployment_qa_execution_target import (
    deployment_qa_execution_target,
)
from yoke_core.domain.deployment_run_member_removal import cmd_remove_item
from yoke_core.domain.qa_plan_management import QaPlanError


@pytest.mark.parametrize("transition", [None, "release"])
def test_attachment_matches_admitted_phase_and_transition(transition):
    rows = [
        {"plan_id": 7, "live": True, "qa_phase": phase, "transition_id": boundary}
        for phase, boundary in [
            ("verification", "reviewing-implementation"),
            ("post_deploy", "other-boundary"),
            ("post_deploy", "release"),
        ]
    ]
    reads = AdmissionReads({}, {}, {1: rows}, {})
    requirement = {
        "plan_id": 7,
        "qa_phase": "post_deploy",
        "workflow_transition_id": transition,
    }
    selected = reads.attachment(1, 7, requirements=[requirement])
    assert selected is rows[2 if transition else 1]
    assert reads.attachment(1, 7, requirements=[]) is rows[0]
    assert reads.attachment(1, 8, requirements=[requirement]) is None


@pytest.mark.parametrize("broken", [False, True])
def test_double_attachment_freezes_release_selection_and_allows_removal(
    test_db, broken
):
    run_id, member = "run-double-attachment", 9971
    plan = _plan(test_db)
    stages = _stages(plan)
    stages[1].pop("cases")
    _seed_run(test_db, run_id=run_id, stages=stages, members=(member,))
    test_db.execute("UPDATE items SET status='release' WHERE id=%s", (member,))
    for transition, phase in [
        ("reviewing-implementation", "verification"),
        ("release", "post_deploy"),
    ]:
        test_db.execute(
            "INSERT INTO qa_plan_item_attachments"
            "(item_id,plan_id,transition_id,qa_phase,attached_at) "
            "VALUES (%s,%s,%s,%s,'2026-10-01T00:00:00Z')",
            (member, plan, transition, phase),
        )
    requirement = insert_qa_requirement(
        test_db,
        item_id=member,
        plan_id=plan,
        qa_phase="post_deploy",
        workflow_transition_id="release",
    )
    raw = snapshot_member_requirements(
        test_db,
        run_id=run_id,
        item_id=member,
        selection_json=requirement_selection(requirement_ids=[requirement["id"]]),
    )
    snapshot = json.loads(raw)
    assert snapshot["plans"][0]["attachment"] == {
        "transition_id": "release",
        "qa_phase": "post_deploy",
    }
    if broken:
        snapshot["plans"][0]["attachment"] = {
            "transition_id": "reviewing-implementation",
            "qa_phase": "verification",
        }
    test_db.execute(
        "UPDATE deployment_run_items SET requirement_snapshot=%s "
        "WHERE run_id=%s AND item_id=%s",
        (json.dumps(snapshot), run_id, member),
    )
    test_db.commit()
    subject = deployment_qa_stage_subject(
        test_db,
        run_id=run_id,
        stage_name="item-qa",
        member_item_id=member,
        require_active=False,
    )
    target = deployment_qa_execution_target(test_db, subject)

    def select():
        return frozen_stage_plans(
            test_db,
            subject,
            target=target,
            admitted=snapshot["requirements"],
        )

    if broken:
        with pytest.raises(QaPlanError, match="qa_frozen_plan_snapshot_incomplete"):
            select()
        release_seeded_driver(test_db, run_id)
        cmd_remove_item(run_id, member, reason="repair admission in a later release")
        assert (
            test_db.execute(
                "SELECT 1 FROM deployment_run_items WHERE run_id=%s AND item_id=%s",
                (run_id, member),
            ).fetchone()
            is None
        )
    else:
        assert [value["plan"]["id"] for value in select()] == [plan]
