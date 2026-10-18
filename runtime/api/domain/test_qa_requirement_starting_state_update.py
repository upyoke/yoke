"""A machine case's starting state is re-declared only before anything ran it."""

from __future__ import annotations

import json
from typing import Any

from runtime.api.fixtures.backlog_inserts import insert_deployment_run, insert_item
from yoke_core.domain.qa_plan_execution_schema import LIVE_PLAN_EXECUTION_STATES
from yoke_core.domain.qa_plan_management import create_plan
from yoke_core.domain.qa_requirement_config_update import apply_requirement_update

RUN_ID = "run-starting-state"
AS_IS = {
    "starting_state": "as_is",
    "starting_state_reason": "keeps the session a person opened",
}
NOW = "2026-10-16T00:00:00Z"


def _mission(conn: Any, *, plan_id: int | None = None, item: bool = False) -> int:
    if item:
        insert_item(conn, id=1, project_sequence=1, workflow_id="issue")
        subject = ("item_id", 1)
    else:
        insert_deployment_run(
            conn,
            id=RUN_ID,
            project_id=1,
            flow="flow-starting-state",
            release_lineage="c" * 40,
            status="executing",
            created_at=NOW,
        )
        subject = ("deployment_run_id", RUN_ID)
    row = conn.execute(
        f"INSERT INTO qa_requirements({subject[0]},qa_kind,qa_phase,method_id,"
        "runner_id,plan_id,host_baseline,starting_state,created_at) VALUES "
        "(%s,'plan_case','post_deploy','exploratory-mission','agent_mission',"
        "%s,'fresh-host','baseline',%s) RETURNING id",
        (subject[1], plan_id, NOW),
    ).fetchone()
    conn.commit()
    return int(row[0])


def _stored(conn: Any, requirement_id: int) -> tuple[Any, ...]:
    return tuple(
        conn.execute(
            "SELECT starting_state, starting_state_reason, host_baseline "
            "FROM qa_requirements WHERE id=%s",
            (requirement_id,),
        ).fetchone()
    )


def _update(conn: Any, requirement_id: int, value: Any):
    return apply_requirement_update(
        conn, requirement_id, "starting_state", json.dumps(value)
    )


def test_unrun_admitted_copy_is_redeclared_as_is_and_back(test_db) -> None:
    plan = create_plan(test_db, project="yoke", slug="human-session")
    requirement_id = _mission(test_db, plan_id=plan["id"])

    result = _update(test_db, requirement_id, AS_IS)

    assert result.ok, result.message
    assert _stored(test_db, requirement_id) == (
        "as_is",
        AS_IS["starting_state_reason"],
        None,
    )
    back = {"starting_state": "baseline", "host_baseline": "shell-preconfigured"}
    assert _update(test_db, requirement_id, back).ok
    assert _stored(test_db, requirement_id) == (
        "baseline",
        None,
        "shell-preconfigured",
    )


def test_impossible_declarations_refuse_by_name(test_db) -> None:
    requirement_id = _mission(test_db)

    missing_reason = _update(test_db, requirement_id, {"starting_state": "as_is"})
    inherit = _update(test_db, requirement_id, {"starting_state": "inherit"})
    unknown = _update(test_db, requirement_id, {**AS_IS, "baseline": "x"})
    not_json = apply_requirement_update(
        test_db, requirement_id, "starting_state", "as_is"
    )

    assert missing_reason.error_code == "payload_invalid"
    assert "starting_state_reason" in missing_reason.message
    assert "yoke qa plan edit" in inherit.message
    assert "unknown keys baseline" in unknown.message
    assert not_json.error_code == "payload_invalid"
    assert _stored(test_db, requirement_id) == ("baseline", None, "fresh-host")


def test_a_recorded_run_closes_the_window(test_db) -> None:
    requirement_id = _mission(test_db)
    test_db.execute(
        "INSERT INTO qa_runs(qa_requirement_id,performed_by,qa_kind,verdict,"
        "verdict_reason,started_at,completed_at,created_at) "
        "VALUES (%s,'agent_mission','plan_case','error','because',%s,%s,%s)",
        (requirement_id, NOW, NOW, NOW),
    )
    test_db.commit()

    result = _update(test_db, requirement_id, AS_IS)

    assert result.error_code == "starting_state_case_executed"
    assert "1 recorded QA runs" in result.message
    assert "yoke qa requirement supersede" in result.message
    assert _stored(test_db, requirement_id) == ("baseline", None, "fresh-host")


def test_a_live_roster_holding_the_case_refuses_with_the_abort(test_db) -> None:
    requirement_id = _mission(test_db)
    test_db.execute(
        "INSERT INTO qa_plan_executions(id,deployment_run_id,session_id,actor_id,"
        "roster_digest,roster_json,cursor_ordinal,state,created_at,heartbeat_at) "
        "VALUES('exec-live',%s,'s-1','1',%s,%s,0,%s,now(),now())",
        (
            RUN_ID,
            "a" * 64,
            json.dumps([{"requirement_id": requirement_id}]),
            sorted(LIVE_PLAN_EXECUTION_STATES)[0],
        ),
    )
    test_db.commit()

    result = _update(test_db, requirement_id, AS_IS)

    assert result.error_code == "starting_state_case_executed"
    assert "live QA execution exec-live" in result.message
    assert "yoke qa plan abort --execution-id exec-live" in result.message


def test_plan_owned_item_row_refuses_toward_the_plan(test_db) -> None:
    plan = create_plan(test_db, project="yoke", slug="plan-owned")
    requirement_id = _mission(test_db, plan_id=plan["id"], item=True)

    result = _update(test_db, requirement_id, AS_IS)

    assert result.error_code == "starting_state_plan_owned"
    assert "yoke qa plan edit" in result.message
    assert _stored(test_db, requirement_id) == ("baseline", None, "fresh-host")
