"""A live stage walk takes corrections to cases it has not reached yet."""

import pytest

from runtime.api.fixtures.backlog_qa_inserts import insert_qa_run
from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
    ITEM_QA_STAGE,
    item_qa_stage_definitions,
    seed_run_standing_on_qa_stage,
)
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.qa_plan_execution_checkin import stop_if_told
from yoke_core.domain.qa_plan_execution_result_state import QaPlanExecutionError
from yoke_core.domain.qa_plan_execution_roster_correction import (
    ROSTER_CASE_REACHED_CODE,
)
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
from yoke_core.domain.qa_plan_rematerialize_deployment import (
    rematerialize_for_deployment_stage,
)

MEMBER = 7316
RUN = "run-roster-correction"
WALKER = "roster-walker"
KEYS = ["prepare", "send", "receive"]


def _case(key, position, instructions):
    return {
        "case_key": key,
        "position": position,
        "method_id": "command",
        "instructions": instructions,
        "expected_outcome": "The command passes.",
        "method_config": {"command": "true"},
    }


def _cases(prepare="Prepare the host.", receive="Receive on one host."):
    return [
        _case("prepare", 1, prepare),
        _case("send", 2, "Send from the host."),
        _case("receive", 3, receive),
    ]


def _seed(conn, *, answered=True):
    """A walk that passed ``prepare``, sits on ``send``, has not reached ``receive``."""
    plan = create_plan(
        conn,
        project="yoke",
        slug="roster-fix",
        name="Roster fix",
        infer_target_environment=False,
    )
    replace_plan_cases(conn, plan_id=plan["id"], cases=_cases())
    stages = item_qa_stage_definitions(int(plan["id"]))
    stages[1]["cases"]["case_keys"] = KEYS
    seed_run_standing_on_qa_stage(
        conn,
        run_id=RUN,
        project="yoke",
        stages=stages,
        members=(MEMBER,),
        lineage="b" * 40,
    )
    materialize_deployment_qa_stage(
        conn,
        deployment_run_id=RUN,
        deployment_stage=ITEM_QA_STAGE,
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
        deployment_stage=ITEM_QA_STAGE,
        deployment_member_item_id=MEMBER,
        actor_id="2",
        session_id=WALKER,
    )


def _refresh(conn):
    return rematerialize_for_deployment_stage(
        conn,
        deployment_run_id=RUN,
        deployment_stage=ITEM_QA_STAGE,
        deployment_member_item_id=MEMBER,
    )


def _instructions(conn, requirement_id):
    return conn.execute(
        "SELECT instructions FROM qa_requirements WHERE id=%s", (requirement_id,)
    ).fetchone()["instructions"]


def test_a_stage_refresh_corrects_only_the_unreached_entry(test_db):
    plan, execution_id, prepared, receiving = _seed(test_db)
    before = lock_plan_execution(test_db, execution_id)
    test_db.commit()
    replace_plan_cases(
        test_db, plan_id=plan, cases=_cases(receive="Receive on two hosts.")
    )
    test_db.commit()

    result = _refresh(test_db)

    assert receiving in result["refreshed_requirement_ids"]
    assert prepared not in result["refreshed_requirement_ids"]
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


def test_correcting_a_case_the_walk_already_walked_refuses(test_db):
    plan, execution_id, prepared, _ = _seed(test_db, answered=False)
    before = lock_plan_execution(test_db, execution_id)
    test_db.commit()
    replace_plan_cases(
        test_db, plan_id=plan, cases=_cases(prepare="Prepare two hosts.")
    )
    test_db.commit()

    with pytest.raises(QaPlanError, match=ROSTER_CASE_REACHED_CODE) as refusal:
        _refresh(test_db)

    assert f"yoke qa plan abort --execution-id {execution_id}" in str(refusal.value)
    assert _instructions(test_db, prepared) == "Prepare the host."
    after = lock_plan_execution(test_db, execution_id)
    test_db.commit()
    assert after["roster_json"] == before["roster_json"]
    assert after["roster_digest"] == before["roster_digest"]
