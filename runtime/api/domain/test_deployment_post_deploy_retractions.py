"""A withdrawn post-deploy plan forms no plan group and withdraws its open one."""

from __future__ import annotations

from contextlib import nullcontext
from unittest.mock import patch

import pytest

from runtime.api.domain.test_qa_plan_item_retract import (
    _attach_post_deploy,
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
from yoke_core.domain.deployment_qa_plan_group_writes import ensure_groups
from yoke_core.domain.deployment_qa_plan_groups import run_groups
from yoke_core.domain.handlers.qa_item_plan_retract import handle_item_retract


def _run(conn, *, run_id: str, item_id: int) -> None:
    seed_run_standing_on_qa_stage(
        conn,
        run_id=run_id,
        project="yoke",
        stages=item_qa_stage_definitions(None),
        members=(item_id,),
        lineage="a" * 40,
    )


def _groups(conn, run_id: str):
    ensure_groups(conn, run_id, ITEM_QA_STAGE)
    conn.commit()
    return run_groups(conn, run_id, ITEM_QA_STAGE)


def _registered_retraction(conn, *, item_id: int, plan_id: int):
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


def _retracted(conn, requirement_ids) -> set[int]:
    return {
        int(row["id"])
        for row in conn.execute(
            "SELECT id FROM qa_requirements WHERE id=ANY(%s) "
            "AND retracted_at IS NOT NULL",
            (list(requirement_ids),),
        ).fetchall()
    }


def test_a_withdrawn_plan_forms_no_group_beside_its_replacement(test_db):
    item_id, run_id = 9860, "run-withdrawn-plan-group"
    _run(test_db, run_id=run_id, item_id=item_id)
    old_plan = _attach_post_deploy(test_db, item_id=item_id, slug="old-group")
    _retract(test_db, item_id=item_id, plan_id=old_plan)
    active_plan = _attach_post_deploy(test_db, item_id=item_id, slug="active-group")

    (group,) = _groups(test_db, run_id)

    assert group.plan_id == active_plan and group.open
    assert (
        test_db.execute(
            "SELECT COUNT(*) FROM qa_requirements WHERE plan_id=%s", (old_plan,)
        ).fetchone()[0]
        == 0
    )


def test_registered_retraction_withdraws_the_open_group_of_its_last_attacher(
    test_db,
):
    item_id, run_id = 9861, "run-retracted-open-group"
    _run(test_db, run_id=run_id, item_id=item_id)
    plan_id = _attach_post_deploy(test_db, item_id=item_id, slug="retracted-group")
    (group,) = _groups(test_db, run_id)

    retracted = _registered_retraction(test_db, item_id=item_id, plan_id=plan_id)

    assert retracted.primary_success
    retired = retracted.result_payload["result"]["retired_requirement_ids"]
    assert sorted(retired) == sorted(group.requirement_ids)
    (after,) = run_groups(test_db, run_id, ITEM_QA_STAGE)
    assert after.retracted and not after.open
    # A retracted group is not replaced while nothing attaches the plan.
    assert _groups(test_db, run_id) == [after]
    assert (
        _registered_retraction(
            test_db, item_id=item_id, plan_id=plan_id
        ).result_payload["result"]["retired_requirement_ids"]
        == []
    )


@pytest.mark.parametrize("verdict", ["pass", "fail"])
def test_retraction_withdraws_an_unpassed_group_but_never_a_passed_row(
    test_db, verdict
):
    item_id, run_id = 9862, f"run-judged-group-{verdict}"
    _run(test_db, run_id=run_id, item_id=item_id)
    plan_id = _attach_post_deploy(test_db, item_id=item_id, slug=f"judged-{verdict}")
    (group,) = _groups(test_db, run_id)
    (requirement_id,) = group.requirement_ids
    record_case_verdict(test_db, requirement_id, verdict, evidence=True)
    test_db.commit()

    retracted = _registered_retraction(test_db, item_id=item_id, plan_id=plan_id)

    assert retracted.primary_success
    expected = set() if verdict == "pass" else {requirement_id}
    assert set(retracted.result_payload["result"]["retired_requirement_ids"]) == expected
    assert _retracted(test_db, group.requirement_ids) == expected
    # The recorded verdict stays as evidence either way.
    assert test_db.execute(
        "SELECT COUNT(*) FROM qa_runs WHERE qa_requirement_id=%s", (requirement_id,)
    ).fetchone()[0]
