"""Withdrawn member QA stays withdrawn at admission and on frozen runs."""

from __future__ import annotations

import json
from contextlib import nullcontext
from unittest.mock import patch

import pytest

from runtime.api.domain.test_deployment_member_post_deploy_admission import (
    ITEM_ID,
    RUN_ID,
    _resolved_ids,
    _run,
)
from runtime.api.domain.test_qa_plan_item_retract import (
    _attach_post_deploy,
    _materialize_item,
    _retract,
)
from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
    ITEM_QA_STAGE,
    item_qa_stage_definitions,
    record_case_verdict,
    seed_run_standing_on_qa_stage,
)
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.deployment_qa_stage_gate import deployment_qa_stage_status
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.deployment_requirement_snapshots import (
    requirement_selection,
    snapshot_member_requirements,
)
from yoke_core.domain.deployment_run_carried_membership import admit_run_item
from yoke_core.domain.handlers.qa_item_plan_retract import handle_item_retract


def _plan_requirement(conn, plan_id: int, item_id: int) -> int:
    row = conn.execute(
        "SELECT id FROM qa_requirements WHERE item_id=%s AND plan_id=%s",
        (item_id, plan_id),
    ).fetchone()
    return int(row["id"])


@pytest.mark.parametrize("source_retracted", [False, True])
def test_admission_selects_only_the_replacement_post_deploy_plan(
    test_db, source_retracted
):
    _run(test_db)
    old_plan = _attach_post_deploy(test_db, item_id=ITEM_ID, slug="old-admission")
    _materialize_item(test_db, item_id=ITEM_ID)
    old_requirement = _plan_requirement(test_db, old_plan, ITEM_ID)
    _retract(test_db, item_id=ITEM_ID, plan_id=old_plan)
    if not source_retracted:
        # A withdrawn attachment alone excludes a copy made by an older build.
        test_db.execute(
            "UPDATE qa_requirements SET retracted_at=NULL WHERE id=%s",
            (old_requirement,),
        )
        test_db.commit()
    active_plan = _attach_post_deploy(test_db, item_id=ITEM_ID, slug="active-admission")
    _materialize_item(test_db, item_id=ITEM_ID)
    active_requirement = _plan_requirement(test_db, active_plan, ITEM_ID)

    admit_run_item(test_db, run_id=RUN_ID, item_id=ITEM_ID)

    assert _resolved_ids(test_db) == [active_requirement]
    frozen = test_db.execute(
        "SELECT requirement_snapshot FROM deployment_run_items WHERE run_id=%s",
        (RUN_ID,),
    ).fetchone()["requirement_snapshot"]
    assert [row["plan_id"] for row in json.loads(frozen)["requirements"]] == [
        active_plan
    ]
    assert old_requirement not in json.loads(frozen)["selection"]["requirement_ids"]


def test_explicit_snapshot_skips_withdrawn_requirements_and_plans(test_db):
    _run(test_db)
    old_plan = _attach_post_deploy(test_db, item_id=ITEM_ID, slug="old-explicit")
    _materialize_item(test_db, item_id=ITEM_ID)
    old_requirement = _plan_requirement(test_db, old_plan, ITEM_ID)
    _retract(test_db, item_id=ITEM_ID, plan_id=old_plan)
    active_plan = _attach_post_deploy(test_db, item_id=ITEM_ID, slug="active-explicit")
    _materialize_item(test_db, item_id=ITEM_ID)
    active_requirement = _plan_requirement(test_db, active_plan, ITEM_ID)

    snapshot = json.loads(
        snapshot_member_requirements(
            test_db,
            run_id=RUN_ID,
            item_id=ITEM_ID,
            selection_json=requirement_selection(
                requirement_ids=(old_requirement, active_requirement),
                plan_ids=(old_plan, active_plan),
            ),
        )
    )

    assert [row["id"] for row in snapshot["requirements"]] == [active_requirement]
    assert [row["plan"]["id"] for row in snapshot["plans"]] == [active_plan]


def _frozen_plan_run(conn, *, run_id: str, item_id: int, include_plan: bool) -> int:
    seed_run_standing_on_qa_stage(
        conn,
        run_id=run_id,
        project="yoke",
        stages=item_qa_stage_definitions(None),
        members=(item_id,),
        lineage="a" * 40,
    )
    plan_id = _attach_post_deploy(conn, item_id=item_id, slug=f"plan-{run_id}")
    _materialize_item(conn, item_id=item_id)
    requirement_id = _plan_requirement(conn, plan_id, item_id)
    snapshot = snapshot_member_requirements(
        conn,
        run_id=run_id,
        item_id=item_id,
        selection_json=requirement_selection(
            requirement_ids=(requirement_id,),
            plan_ids=(plan_id,) if include_plan else (),
        ),
    )
    conn.execute(
        "UPDATE deployment_run_items SET requirement_snapshot=%s WHERE run_id=%s",
        (snapshot, run_id),
    )
    conn.commit()
    return plan_id


@pytest.mark.parametrize("include_plan", [False, True])
def test_a_frozen_withdrawn_plan_does_not_rematerialize(test_db, include_plan):
    item_id = 9860
    run_id = "run-frozen-withdrawal"
    old_plan = _frozen_plan_run(
        test_db,
        run_id=run_id,
        item_id=item_id,
        include_plan=include_plan,
    )
    _retract(test_db, item_id=item_id, plan_id=old_plan)
    active_plan = _attach_post_deploy(test_db, item_id=item_id, slug="active-frozen")

    result = materialize_deployment_qa_stage(
        test_db,
        deployment_run_id=run_id,
        deployment_stage=ITEM_QA_STAGE,
        deployment_member_item_id=item_id,
    )

    rows = test_db.execute(
        "SELECT plan_id FROM qa_requirements WHERE deployment_run_id=%s "
        "AND deployment_member_item_id=%s AND method_id IS NOT NULL",
        (run_id, item_id),
    ).fetchall()
    assert result["created_requirement_ids"]
    assert {row["plan_id"] for row in rows} == {active_plan}
    status = deployment_qa_stage_status(
        test_db,
        run_id=run_id,
        stage_name=ITEM_QA_STAGE,
        member_item_id=item_id,
    )
    assert not status["accepted"]  # The replacement still owes its own evidence.


def _repeat_registered_retraction(conn, *, item_id: int, plan_id: int):
    request = FunctionCallRequest(
        function="qa.item_plan.retract",
        actor=ActorContext(actor_id="op", session_id="test-session"),
        target=TargetRef(kind="item", item_id=item_id),
        payload={
            "project": "yoke",
            "plan_id": plan_id,
            "transition_id": "release",
            "reason": "withdraw the mis-scoped post-deploy plan",
            "source": "agent",
        },
    )
    with patch("yoke_core.domain.db_helpers.connect", return_value=nullcontext(conn)):
        return handle_item_retract(request)


def test_registered_retraction_settles_copies_admitted_after_withdrawal(test_db):
    item_id = 9861
    run_id = "run-late-withdrawn-copy"
    plan_id = _frozen_plan_run(
        test_db,
        run_id=run_id,
        item_id=item_id,
        include_plan=True,
    )
    result = materialize_deployment_qa_stage(
        test_db,
        deployment_run_id=run_id,
        deployment_stage=ITEM_QA_STAGE,
        deployment_member_item_id=item_id,
    )
    copy_id = result["created_requirement_ids"][0]
    _retract(test_db, item_id=item_id, plan_id=plan_id)
    original = test_db.execute(
        "SELECT retracted_at,retraction_rationale FROM qa_plan_item_attachments "
        "WHERE item_id=%s AND plan_id=%s",
        (item_id, plan_id),
    ).fetchone()
    # Reproduce a copy materialized by an older build after the withdrawal.
    test_db.execute(
        "UPDATE qa_requirements SET retracted_at=NULL WHERE id=%s", (copy_id,)
    )
    test_db.commit()
    before = deployment_qa_stage_status(
        test_db,
        run_id=run_id,
        stage_name=ITEM_QA_STAGE,
        member_item_id=item_id,
    )
    assert not before["accepted"]

    repaired = _repeat_registered_retraction(test_db, item_id=item_id, plan_id=plan_id)

    assert repaired.primary_success
    assert repaired.result_payload["result"]["retired_requirement_ids"] == [copy_id]
    row = test_db.execute(
        "SELECT retracted_at,waived_at,superseded_by_requirement_id "
        "FROM qa_requirements WHERE id=%s",
        (copy_id,),
    ).fetchone()
    assert row["retracted_at"]
    assert row["waived_at"] is None
    assert row["superseded_by_requirement_id"] is None
    after = deployment_qa_stage_status(
        test_db,
        run_id=run_id,
        stage_name=ITEM_QA_STAGE,
        member_item_id=item_id,
    )
    assert after["accepted"]
    assert (
        _repeat_registered_retraction(
            test_db, item_id=item_id, plan_id=plan_id
        ).result_payload["result"]["retired_requirement_ids"]
        == []
    )
    retained = test_db.execute(
        "SELECT retracted_at,retraction_rationale FROM qa_plan_item_attachments "
        "WHERE item_id=%s AND plan_id=%s",
        (item_id, plan_id),
    ).fetchone()
    assert dict(retained) == dict(original)


def test_retraction_repair_still_refuses_a_passing_late_copy(test_db):
    item_id = 9862
    run_id = "run-passing-withdrawn-copy"
    plan_id = _frozen_plan_run(
        test_db,
        run_id=run_id,
        item_id=item_id,
        include_plan=False,
    )
    result = materialize_deployment_qa_stage(
        test_db,
        deployment_run_id=run_id,
        deployment_stage=ITEM_QA_STAGE,
        deployment_member_item_id=item_id,
    )
    copy_id = result["created_requirement_ids"][0]
    _retract(test_db, item_id=item_id, plan_id=plan_id)
    test_db.execute(
        "UPDATE qa_requirements SET retracted_at=NULL WHERE id=%s", (copy_id,)
    )
    record_case_verdict(test_db, copy_id, "pass", evidence=True)

    repaired = _repeat_registered_retraction(test_db, item_id=item_id, plan_id=plan_id)

    assert not repaired.primary_success
    assert "already recorded a passing verdict" in repaired.error.message
    assert (
        test_db.execute(
            "SELECT retracted_at FROM qa_requirements WHERE id=%s",
            (copy_id,),
        ).fetchone()["retracted_at"]
        is None
    )
