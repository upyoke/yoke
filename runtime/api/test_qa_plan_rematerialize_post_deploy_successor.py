"""A corrected post_deploy case supersedes the row it replaced, never a waiver.

When a worker corrects its plan after admission, rematerializing the item
retires the old case's rows. A waiver there claimed the proof was not needed
and left the corrected rows with nothing linking them to the old ones; the
supersession says the corrected row now carries the obligation, so the
corrected case's passing run copies close the item.
"""

from runtime.api.domain.test_dash_post_deploy_done_consumption import _accept_member_qa
from runtime.api.test_qa_case_environment_obligations import (
    CASE,
    ITEM_ID,
    _requirements,
    _run,
    _setup,
)
from yoke_core.domain.deployment_qa_source_obligation import (
    source_obligation_consumed,
    unsatisfied_blocking,
)
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.qa_plan_attachments import materialize_for_item
from yoke_core.domain.qa_plan_management import replace_plan_cases
from yoke_core.domain.qa_requirement_source_retirement import (
    admitted_source_correction,
)
from yoke_core.domain.qa_plan_rematerialize import (
    SUCCESSOR_RATIONALE,
    rematerialize_for_item,
)

CORRECTED = {
    **CASE,
    "case_key": "corrected-environment-proof",
    "instructions": "Run the corrected command against the case target.",
}


def _rows(conn, ids):
    return {
        int(row["id"]): dict(row)
        for row in conn.execute(
            "SELECT id,target_env,waived_at,superseded_by_requirement_id,"
            "supersession_rationale,supersession_source FROM qa_requirements "
            "WHERE id = ANY(%s)",
            (list(ids),),
        ).fetchall()
    }


def _live_by_env(conn):
    return {
        row["target_env"]: int(row["id"])
        for row in conn.execute(
            "SELECT id,target_env FROM qa_requirements WHERE item_id=%s "
            "AND deployment_run_id IS NULL AND plan_case_key=%s",
            (ITEM_ID, CORRECTED["case_key"]),
        ).fetchall()
    }


def _correct(conn, plan, cases):
    replace_plan_cases(conn, plan_id=plan["id"], cases=cases)
    return rematerialize_for_item(conn, item_id=ITEM_ID, transition_id="release")


def test_replaced_case_rows_are_superseded_per_environment(test_db):
    item, plan, _case = _setup(test_db)
    materialize_for_item(test_db, item_id=item["id"], transition_id="release")
    old = {env: row["id"] for env, row in _requirements(test_db).items()}

    result = _correct(test_db, plan, [CORRECTED])

    new = _live_by_env(test_db)
    assert set(new) == {"stage", "prod"}
    assert result["waived_requirement_ids"] == []
    assert result["superseded_requirement_ids"] == {
        old["stage"]: new["stage"],
        old["prod"]: new["prod"],
    }
    rows = _rows(test_db, old.values())
    for env, old_id in old.items():
        assert rows[old_id]["waived_at"] is None
        assert rows[old_id]["superseded_by_requirement_id"] == new[env]
        assert rows[old_id]["supersession_source"] == "system"
        assert rows[old_id]["supersession_rationale"] == SUCCESSOR_RATIONALE.format(
            successor_id=new[env]
        )

    # Converged: a second pass neither waives nor re-links the retired rows.
    again = rematerialize_for_item(test_db, item_id=ITEM_ID, transition_id="release")
    assert again["waived_requirement_ids"] == []
    assert again["superseded_requirement_ids"] == {}
    assert set(again["refreshed_requirement_ids"]) == set(new.values())


def test_corrected_run_copies_close_the_item_without_a_waiver(test_db):
    item, plan, _case = _setup(test_db)
    materialize_for_item(test_db, item_id=item["id"], transition_id="release")
    _correct(test_db, plan, [CORRECTED])
    new = _live_by_env(test_db)

    for env in ("prod", "stage"):
        run_id = f"run-successor-{env}"
        _run(test_db, name=run_id, requirement_id=new[env], environment=env)
        _accept_member_qa(test_db, run_id=run_id, item_id=ITEM_ID)
        assert source_obligation_consumed(
            test_db, item_id=ITEM_ID, source_requirement_id=new[env]
        )

    blocking = unsatisfied_blocking(test_db, item_id=ITEM_ID, target_status="done")
    assert blocking.count == 0, blocking.rows
    waived = test_db.execute(
        "SELECT COUNT(*) FROM qa_requirements WHERE item_id=%s AND waived_at IS NOT NULL",
        (ITEM_ID,),
    ).fetchone()[0]
    assert waived == 0


def test_dropped_case_without_a_single_successor_is_waived(test_db):
    item, plan, case = _setup(test_db)
    materialize_for_item(test_db, item_id=item["id"], transition_id="release")
    old = {env: row["id"] for env, row in _requirements(test_db).items()}
    second = {**CORRECTED, "case_key": "second-environment-proof"}

    # Two new cases could each claim the old rows: neither is chosen.
    result = _correct(test_db, plan, [CORRECTED, second])

    assert result["superseded_requirement_ids"] == {}
    assert sorted(result["waived_requirement_ids"]) == sorted(old.values())
    assert all(
        row["superseded_by_requirement_id"] is None
        for row in _rows(test_db, old.values()).values()
    )


def test_case_dropped_from_one_environment_is_waived_there(test_db):
    item, plan, case = _setup(test_db)
    materialize_for_item(test_db, item_id=item["id"], transition_id="release")
    old = {env: row["id"] for env, row in _requirements(test_db).items()}

    result = _correct(
        test_db, plan, [{**CORRECTED, "target_envs": ["prod"], "stage_reason": None}]
    )

    new = _live_by_env(test_db)
    assert set(new) == {"prod"}
    assert result["superseded_requirement_ids"] == {old["prod"]: new["prod"]}
    assert result["waived_requirement_ids"] == [old["stage"]]


def test_plain_materialize_after_replacement_keeps_the_snapshot_until_rematerialize(test_db):
    item, plan, _case = _setup(test_db)
    materialize_for_item(test_db, item_id=item["id"], transition_id="release")
    old = sorted(row["id"] for row in _requirements(test_db).values())
    replace_plan_cases(test_db, plan_id=plan["id"], cases=[CORRECTED])

    before = _rows(test_db, old)
    unchanged = materialize_for_item(
        test_db, item_id=item["id"], transition_id="release"
    )
    assert unchanged["created_requirement_ids"] == []
    assert unchanged["existing_requirement_ids"] == old
    assert _rows(test_db, old) == before

    result = rematerialize_for_item(test_db, item_id=ITEM_ID, transition_id="release")
    assert sorted(result["superseded_requirement_ids"]) == old


def test_superseding_a_plan_copy_names_the_member_plan_row_to_retire(test_db):
    item, plan, case = _setup(test_db)
    materialize_for_item(test_db, item_id=item["id"], transition_id="release")
    source = _requirements(test_db)["prod"]["id"]
    copy = {
        "id": 990001,
        "deployment_run_id": "run-plan-copy",
        "deployment_member_item_id": ITEM_ID,
        "plan_id": plan["id"],
        "plan_case_key": f"{case['case_key']}@0123456789ab",
        "target_env": "prod",
        "host_baseline": None,
    }

    named = admitted_source_correction(test_db, copy)

    assert named["admitted_from_requirement_id"] == source
    notice = named["next_admission_notice"]
    assert f"materialized from QA plan {plan['id']}" in notice
    assert (
        f"yoke qa plan rematerialize --item {render_item_ref(test_db, ITEM_ID)}"
        in notice
    )
    assert "--transition release" in notice

    _correct(test_db, plan, [CORRECTED])
    assert admitted_source_correction(test_db, copy) == {}
