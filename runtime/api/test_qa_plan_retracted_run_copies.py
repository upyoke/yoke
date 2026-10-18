"""A plan whose only run copies were retracted is still owed by its item.

Retraction withdraws a copy from its run, as when the member left the run;
it answers nothing for the member, passed or not. Counting it as answered
let a rematerialize retire the item's live row for a changed case without
creating its successor, and a later materialize then found nothing owed.
"""

from runtime.api.test_qa_case_environment_obligations import (
    ITEM_ID,
    _requirements,
    _setup,
)
from yoke_core.domain.qa_deployment_member_attached_plans import (
    delivery_answered_plan_ids,
)
from yoke_core.domain.qa_plan_attachments import materialize_for_item
from yoke_core.domain.qa_plan_management import replace_plan_cases
from yoke_core.domain.qa_plan_rematerialize import rematerialize_for_item

RUN = "run-member-removed"


def _retracted_run_copies(conn, *, passed):
    """One retracted as-is run copy per environment, as a removed member leaves."""
    for (copy_id,) in conn.execute(
        "INSERT INTO qa_requirements(deployment_run_id,deployment_stage,"
        "deployment_member_item_id,qa_kind,qa_phase,target_env,blocking_mode,"
        "plan_id,plan_case_key,host_baseline,method_id,created_at,retracted_at,"
        "retraction_rationale,retraction_source) "
        "SELECT %s,'item-qa',%s,qa_kind,qa_phase,target_env,blocking_mode,plan_id,"
        "plan_case_key,NULL,method_id,now(),now(),'member left the run','system' "
        "FROM qa_requirements WHERE item_id=%s AND deployment_run_id IS NULL "
        "RETURNING id",
        (RUN, ITEM_ID, ITEM_ID),
    ).fetchall():
        if passed:
            conn.execute(
                "INSERT INTO qa_runs(qa_requirement_id,performed_by,qa_kind,verdict,"
                "raw_result,started_at,completed_at,created_at) VALUES "
                "(%s,'agent','plan_case','pass','ok',now(),now(),now())",
                (copy_id,),
            )
    conn.commit()


def _as_is(case):
    return {
        **case,
        "host_baselines": [],
        "starting_state": "as_is",
        "starting_state_reason": "The mission inspects the host it is given.",
    }


def test_changed_baseline_keeps_its_obligation_when_run_copies_were_retracted(
    test_db,
):
    item, plan, case = _setup(test_db, baselines=("fresh-host",))
    materialize_for_item(test_db, item_id=item["id"], transition_id="release")
    old = {env: row["id"] for env, row in _requirements(test_db).items()}
    replace_plan_cases(test_db, plan_id=plan["id"], cases=[_as_is(case)])
    for passed in (False, True):
        _retracted_run_copies(test_db, passed=passed)
    assert (
        delivery_answered_plan_ids(
            test_db, member_item_id=ITEM_ID, plan_ids=[plan["id"]]
        )
        == set()
    )

    result = rematerialize_for_item(
        test_db, item_id=item["id"], transition_id="release"
    )

    live = test_db.execute(
        "SELECT id,target_env,host_baseline FROM qa_requirements WHERE item_id=%s "
        "AND deployment_run_id IS NULL AND waived_at IS NULL",
        (ITEM_ID,),
    ).fetchall()
    assert {(row["target_env"], row["host_baseline"]) for row in live} == {
        ("stage", None),
        ("prod", None),
    }
    assert sorted(result["created_requirement_ids"]) == sorted(
        row["id"] for row in live
    )
    assert sorted(result["waived_requirement_ids"]) == sorted(old.values())

    again = materialize_for_item(test_db, item_id=item["id"], transition_id="release")
    assert again["plan_ids"] == [plan["id"]]
    assert again["created_requirement_ids"] == []
    assert {row["id"] for row in live} <= set(again["existing_requirement_ids"])
