"""Durable mission hand-back and governed execution-state cutover."""

from runtime.api.domain.qa_execution_walk_states_test_support import (
    assert_walking_proof as assert_walking_proof,
    record_handback as record_handback,
)


import json
from unittest.mock import patch


from runtime.api.fixtures.qa_captured_plan_review_fixture import captured_plan_review
from yoke_core.domain.agent_mission_restore import (
    commit_mission_handback,
    post_capture_state,
)
from yoke_core.domain.qa_plan_execution_store import lock_plan_execution, roster_digest


def _capture(conn, item_id):
    existing = conn.execute(
        "SELECT 1 FROM project_capabilities WHERE type LIKE 'test-machine%' LIMIT 1"
    ).fetchone()
    if existing is None:
        return captured_plan_review(conn, item_id)
    with patch(
        "runtime.api.fixtures.qa_captured_plan_review_fixture.replace_test_machine_settings"
    ):
        return captured_plan_review(conn, item_id)


def _mission(conn, item_id):
    execution, requirement_id, run_id = _capture(conn, item_id)
    execution["roster"][0]["runner_id"] = "agent_mission"
    execution["roster"][0]["method_config"]["os"] = "macos"
    conn.execute(
        "UPDATE qa_plan_executions SET roster_json=%s,roster_digest=%s,state='walking' WHERE id=%s",
        (
            json.dumps(execution["roster"]),
            roster_digest(execution["roster"]),
            execution["id"],
        ),
    )
    conn.execute(
        "UPDATE qa_plan_execution_results SET result_json=%s WHERE execution_id=%s",
        (json.dumps({"run_id": run_id}), execution["id"]),
    )
    conn.commit()
    return lock_plan_execution(conn, execution["id"]), requirement_id, run_id


def _restore(conn, run_id):
    conn.execute(
        "INSERT INTO qa_artifacts(qa_run_id,artifact_type,artifact_handle,created_at) "
        "VALUES(%s,'starting_state_restore','{}','2026-10-21T00:00:00Z')",
        (run_id,),
    )


def _state_indexes(conn):
    return dict(
        conn.execute(
            "SELECT indexname,indexdef FROM pg_indexes WHERE schemaname=current_schema() "
            "AND tablename='qa_plan_executions' AND indexdef LIKE '%%state%%'"
        ).fetchall()
    )


def test_last_mission_handback_changes_state_atomically_and_retry_is_safe(test_db):
    execution, requirement_id, first_run = _mission(test_db, 91004)
    _, second_requirement, second_run = _capture(test_db, 91005)
    roster = execution["roster"] + [
        {
            **execution["roster"][0],
            "requirement_id": second_requirement,
        }
    ]
    test_db.execute(
        "UPDATE qa_plan_executions SET roster_json=%s,roster_digest=%s,cursor_ordinal=2 WHERE id=%s",
        (json.dumps(roster), roster_digest(roster), execution["id"]),
    )
    test_db.execute(
        "INSERT INTO qa_plan_execution_results(execution_id,ordinal,requirement_id,"
        "result_json,completed_at) VALUES(%s,1,%s,%s,'2026-10-21T00:00:00Z')",
        (execution["id"], second_requirement, json.dumps({"run_id": second_run})),
    )
    _restore(test_db, first_run)
    commit_mission_handback(
        test_db, artifact_type="starting_state_restore", run_id=first_run
    )
    current = lock_plan_execution(test_db, execution["id"])
    assert current["state"] == post_capture_state(test_db, current) == "walking"
    _restore(test_db, second_run)
    commit_mission_handback(
        test_db, artifact_type="starting_state_restore", run_id=second_run
    )
    current = lock_plan_execution(test_db, execution["id"])
    assert (
        current["state"]
        == post_capture_state(test_db, current)
        == "awaiting_walk_review"
    )
    assert current["completed_at"] is None
    commit_mission_handback(
        test_db, artifact_type="starting_state_restore", run_id=second_run
    )
    assert (
        lock_plan_execution(test_db, execution["id"])["state"] == "awaiting_walk_review"
    )


def test_non_restore_artifact_and_ordinary_capture_do_not_start_a_walk(test_db):
    execution, _, run_id = _mission(test_db, 91006)
    commit_mission_handback(test_db, artifact_type="diagnostic", run_id=run_id)
    assert lock_plan_execution(test_db, execution["id"])["state"] == "walking"
    ordinary, _, _ = _capture(test_db, 91007)
    assert post_capture_state(test_db, ordinary) == "awaiting_walk_review"


def test_stopped_capture_keeps_the_independent_review_cue(test_db):
    from yoke_core.domain.qa_plan_review import begin_plan_review
    from yoke_core.domain.qa_plan_case_proof import _case_result
    from yoke_core.domain.qa_plan_execution_lifecycle import finish_plan_execution

    execution, _, _ = _capture(test_db, 91008)
    bundle = begin_plan_review(test_db, execution)
    assert bundle is not None
    finish_plan_execution(test_db, execution, state="aborted", reason="stop capture")
    case = execution["roster"][0]
    proof = _case_result(
        test_db,
        plan_id=case["plan_id"],
        case_key=case["case_key"],
        host_baseline=None,
        deployment_run_id=None,
    )
    assert proof["review"]["state"] == "awaiting_walk_review"
