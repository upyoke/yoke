"""A live stage walk takes corrections to cases it has not reached yet."""

import pytest

from runtime.api.domain.test_deployment_qa_stage_execution import _environment
from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.backlog_qa_inserts import insert_qa_run
from runtime.api.fixtures.completed_delivery import (
    seed_selected_requirement_run as _seed_selected_requirement_run,
)
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.qa_plan_attachments import (
    attach_plan_to_item,
    materialize_for_item,
)
from yoke_core.domain.qa_plan_execution_checkin import stop_if_told
from yoke_core.domain.qa_plan_execution_result_state import QaPlanExecutionError
from yoke_core.domain.qa_plan_execution_state import (
    advance_plan_execution,
    begin_plan_execution,
    lock_plan_execution,
)
from yoke_core.domain.qa_plan_execution_store import roster_digest
from yoke_core.domain.qa_plan_management import (
    QaPlanError,
    create_plan,
    replace_plan_cases,
)
from yoke_core.domain.qa_plan_rematerialize import rematerialize_for_item
from yoke_core.domain.qa_plan_rematerialize_deployment import (
    rematerialize_for_deployment_stage,
)

MEMBER = 7316
RUN = "run-roster-correction"
STAGE = "member-qa"
WALKER = "roster-walker"


def _case(key, position, instructions):
    return {
        "case_key": key,
        "position": position,
        "method_id": "command",
        "instructions": instructions,
        "expected_outcome": "The command passes.",
        "method_config": {"command": "true"},
        "target_envs": ["stage"],
        "stage_reason": "creates_or_destroys_data",
    }


def _cases(prepare="Prepare the host.", receive="Receive on one host."):
    return [
        _case("prepare", 1, prepare),
        _case("send", 2, "Send from the host."),
        _case("receive", 3, receive),
    ]


def _seed(conn, *, answered=True):
    """A walk that passed ``prepare``, sits on ``send``, has not reached ``receive``."""
    _environment(conn)
    item = insert_item(conn, id=MEMBER, workflow_id="issue", status="release")
    plan = create_plan(conn, project="yoke", slug="roster-fix", name="Roster fix")
    replace_plan_cases(conn, plan_id=plan["id"], cases=_cases())
    attach_plan_to_item(
        conn,
        item_id=item["id"],
        plan_id=plan["id"],
        transition_id="release",
        qa_phase="post_deploy",
    )
    sources = materialize_for_item(conn, item_id=MEMBER, transition_id="release")[
        "created_requirement_ids"
    ]
    _seed_selected_requirement_run(
        conn,
        run_id=RUN,
        item_id=MEMBER,
        requirement_id=sources[0],
        also_selected=tuple(sources[1:]),
    )
    materialize_deployment_qa_stage(
        conn,
        deployment_run_id=RUN,
        deployment_stage=STAGE,
        deployment_member_item_id=MEMBER,
    )
    execution = _begin(conn)
    prepared, _, receiving = (
        int(case["requirement_id"]) for case in execution["roster"]
    )
    if answered:
        insert_qa_run(conn, qa_requirement_id=prepared, verdict="pass")
    advance_plan_execution(
        conn,
        lock_plan_execution(conn, execution["id"]),
        ordinal=0,
        requirement_id=prepared,
        result={"requirement_id": prepared, "case_outcome": "passed"},
    )
    return int(plan["id"]), str(execution["id"]), prepared, receiving


def _begin(conn):
    return begin_plan_execution(
        conn,
        deployment_run_id=RUN,
        deployment_stage=STAGE,
        deployment_member_item_id=MEMBER,
        actor_id="2",
        session_id=WALKER,
    )


def _instructions(conn, requirement_id):
    return conn.execute(
        "SELECT instructions FROM qa_requirements WHERE id=%s", (requirement_id,)
    ).fetchone()["instructions"]


def test_correcting_an_unreached_case_updates_the_live_roster(test_db):
    plan, execution_id, prepared, receiving = _seed(test_db)
    before = lock_plan_execution(test_db, execution_id)
    test_db.commit()
    replace_plan_cases(
        test_db, plan_id=plan, cases=_cases(receive="Receive on two hosts.")
    )
    test_db.commit()

    result = rematerialize_for_item(test_db, item_id=MEMBER, transition_id="release")

    assert receiving in result["corrected_admitted_copy_ids"]
    assert prepared not in result["corrected_admitted_copy_ids"]
    assert _instructions(test_db, receiving) == "Receive on two hosts."
    after = lock_plan_execution(test_db, execution_id)
    test_db.commit()
    assert after["state"] == "active" and after["cursor_ordinal"] == 1
    assert after["roster"][:2] == before["roster"][:2]
    assert after["roster"][2]["instructions"] == "Receive on two hosts."
    assert after["roster_digest"] == roster_digest(after["roster"])
    assert after["roster_digest"] != before["roster_digest"]
    # The walker resumes the same execution on the corrected roster: the
    # passed case keeps its result and is not replayed.
    resumed = _begin(test_db)
    assert str(resumed["id"]) == execution_id
    assert resumed["roster_digest"] == after["roster_digest"]
    results = test_db.execute(
        "SELECT ordinal,requirement_id FROM qa_plan_execution_results "
        "WHERE execution_id=%s",
        (execution_id,),
    ).fetchall()
    assert [(row["ordinal"], row["requirement_id"]) for row in results] == [
        (0, prepared)
    ]
    # A walker still holding the old roster stops at its next check-in.
    with pytest.raises(QaPlanExecutionError, match="qa_roster_corrected"):
        stop_if_told(
            {"roster_digest": after["roster_digest"]},
            {"execution_id": execution_id, "roster_digest": before["roster_digest"]},
        )


def test_a_stage_refresh_corrects_only_the_unreached_entry(test_db):
    plan, execution_id, prepared, receiving = _seed(test_db)
    before = lock_plan_execution(test_db, execution_id)
    test_db.commit()
    replace_plan_cases(
        test_db, plan_id=plan, cases=_cases(receive="Receive on two hosts.")
    )
    test_db.commit()

    rematerialize_for_deployment_stage(
        test_db,
        deployment_run_id=RUN,
        deployment_stage=STAGE,
        deployment_member_item_id=MEMBER,
    )

    after = lock_plan_execution(test_db, execution_id)
    test_db.commit()
    assert after["roster"][:2] == before["roster"][:2]
    assert after["roster"][2]["instructions"] == "Receive on two hosts."
    assert after["roster_digest"] == roster_digest(after["roster"])
    assert str(_begin(test_db)["id"]) == execution_id


@pytest.mark.parametrize(
    "answered,recovery",
    [(True, "yoke qa requirement supersede"), (False, "yoke qa plan abort")],
)
def test_correcting_a_case_the_walk_already_ran_refuses(test_db, answered, recovery):
    plan, execution_id, prepared, _ = _seed(test_db, answered=answered)
    before = lock_plan_execution(test_db, execution_id)
    test_db.commit()
    replace_plan_cases(
        test_db, plan_id=plan, cases=_cases(prepare="Prepare two hosts.")
    )
    test_db.commit()

    with pytest.raises(QaPlanError, match="admitted_copy_in_flight") as refusal:
        rematerialize_for_item(test_db, item_id=MEMBER, transition_id="release")

    # An answered copy is frozen for good; one only walked can be re-walked.
    assert f"admitted case {prepared}" in str(refusal.value)
    assert recovery in str(refusal.value)
    assert _instructions(test_db, prepared) == "Prepare the host."
    after = lock_plan_execution(test_db, execution_id)
    test_db.commit()
    assert after["roster_json"] == before["roster_json"]
    assert after["roster_digest"] == before["roster_digest"]
