"""Durable mission hand-back and governed execution-state cutover."""

import importlib
import base64
import json
from unittest.mock import patch

import pytest

from runtime.api.fixtures.qa_captured_plan_review_fixture import captured_plan_review
from yoke_core.domain import db_backend
from yoke_core.domain.agent_mission_restore import (
    commit_mission_handback,
    post_capture_state,
)
from yoke_core.domain.migration_serving_version import NEXT_RELEASE
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


MIGRATION = importlib.import_module(
    "yoke_core.domain.migrations.0089_qa_execution_walk_states"
)
EARLIER_MIGRATIONS = tuple(importlib.import_module(
    f"yoke_core.domain.migrations.{name}"
) for name in (
    "0049_standalone_qa_plan_execution", "0088_shared_qa_execution_per_session",
))


def _mission(conn, item_id):
    execution, requirement_id, run_id = _capture(conn, item_id)
    execution["roster"][0]["runner_id"] = "agent_mission"
    execution["roster"][0]["method_config"]["os"] = "macos"
    conn.execute(
        "UPDATE qa_plan_executions SET roster_json=%s,roster_digest=%s,state='walking' WHERE id=%s",
        (json.dumps(execution["roster"]), roster_digest(execution["roster"]), execution["id"]),
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
    return dict(conn.execute(
        "SELECT indexname,indexdef FROM pg_indexes WHERE schemaname=current_schema() "
        "AND tablename='qa_plan_executions' AND indexdef LIKE '%%state%%'"
    ).fetchall())


def _old_contract(conn):
    conn.execute(
        "ALTER TABLE qa_plan_executions DROP CONSTRAINT qa_plan_executions_state_check"
    )
    conn.execute(
        "UPDATE qa_plan_executions SET state='awaiting_agent_review' "
        "WHERE state IN ('walking','awaiting_walk_review')"
    )
    conn.execute(
        "ALTER TABLE qa_plan_executions ADD CONSTRAINT qa_plan_executions_state_check "
        "CHECK(state IN ('active','waiting','awaiting_agent_review',"
        "'completed','aborted','error'))"
    )
    for name, definition in conn.execute(
        "SELECT indexname,indexdef FROM pg_indexes WHERE schemaname=current_schema() "
        "AND tablename='qa_plan_executions'"
    ).fetchall():
        if "'walking'" not in definition:
            continue
        conn.execute(f'DROP INDEX "{name}"')
        conn.execute(definition.replace(", 'walking'::text", "").replace(
            "'awaiting_walk_review'", "'awaiting_agent_review'"
        ))
    conn.commit()
    # Live pre-0089 tenants store sorted arrays, except the item-scoped index.
    for name, definition in _state_indexes(conn).items():
        assert "'walking'" not in definition
        assert ("'active'::text, 'waiting'::text, 'awaiting_agent_review'::text"
                if name == "idx_qa_plan_executions_active" else
                "'active'::text, 'awaiting_agent_review'::text, 'waiting'::text"
                ) in definition


def test_migration_classifies_old_rows_and_preserves_custody(test_db):
    walking, _, _ = _mission(test_db, 91001)
    restored, _, restored_run = _mission(test_db, 91002)
    ordinary, _, _ = _capture(test_db, 91003)
    test_db.execute(
        "UPDATE qa_plan_executions SET state='awaiting_walk_review' WHERE id=%s",
        (ordinary["id"],),
    )
    _restore(test_db, restored_run)
    # Reconstruct the pre-cutover index retired by the later target migration.
    EARLIER_MIGRATIONS[1].apply(test_db)
    _old_contract(test_db)
    before = dict(test_db.execute(
        "SELECT id,execution_target_digest FROM qa_plan_executions"
    ).fetchall())
    MIGRATION.apply(test_db)
    MIGRATION.invariants(test_db)
    MIGRATION.apply(test_db)
    MIGRATION.invariants(test_db)
    for earlier in EARLIER_MIGRATIONS:
        earlier.invariants(test_db)
    target_migration = importlib.import_module(
        "yoke_core.domain.migrations.0096_qa_execution_target_scope"
    )
    target_migration.apply(test_db)
    target_migration.invariants(test_db)
    MIGRATION.invariants(test_db)
    assert MIGRATION.MINIMUM_SERVING_VERSION == NEXT_RELEASE
    rows = dict(test_db.execute("SELECT id,state FROM qa_plan_executions").fetchall())
    assert rows[walking["id"]] == "walking"
    assert rows[restored["id"]] == "awaiting_walk_review"
    assert rows[ordinary["id"]] == "awaiting_walk_review"
    assert dict(test_db.execute(
        "SELECT id,execution_target_digest FROM qa_plan_executions"
    ).fetchall()) == before
    test_db.execute("SAVEPOINT duplicate_live")
    with pytest.raises(db_backend.integrity_error_types(test_db)):
        test_db.execute(
            "INSERT INTO qa_plan_executions(id,item_id,transition_id,session_id,"
            "roster_digest,roster_json,state,created_at,heartbeat_at) "
            "SELECT 'duplicate',item_id,transition_id,'another','digest','[]',"
            "'walking',created_at,heartbeat_at FROM qa_plan_executions WHERE id=%s",
            (walking["id"],),
        )
    test_db.execute("ROLLBACK TO SAVEPOINT duplicate_live")


def test_last_mission_handback_changes_state_atomically_and_retry_is_safe(test_db):
    execution, requirement_id, first_run = _mission(test_db, 91004)
    _, second_requirement, second_run = _capture(test_db, 91005)
    roster = execution["roster"] + [{
        **execution["roster"][0], "requirement_id": second_requirement,
    }]
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
    commit_mission_handback(test_db, artifact_type="starting_state_restore", run_id=first_run)
    current = lock_plan_execution(test_db, execution["id"])
    assert current["state"] == post_capture_state(test_db, current) == "walking"
    _restore(test_db, second_run)
    commit_mission_handback(test_db, artifact_type="starting_state_restore", run_id=second_run)
    current = lock_plan_execution(test_db, execution["id"])
    assert current["state"] == post_capture_state(test_db, current) == "awaiting_walk_review"
    assert current["completed_at"] is None
    commit_mission_handback(test_db, artifact_type="starting_state_restore", run_id=second_run)
    assert lock_plan_execution(test_db, execution["id"])["state"] == "awaiting_walk_review"


def test_non_restore_artifact_and_ordinary_capture_do_not_start_a_walk(test_db):
    execution, _, run_id = _mission(test_db, 91006)
    commit_mission_handback(test_db, artifact_type="diagnostic", run_id=run_id)
    assert lock_plan_execution(test_db, execution["id"])["state"] == "walking"
    ordinary, _, _ = _capture(test_db, 91007)
    assert post_capture_state(test_db, ordinary) == "awaiting_walk_review"


def record_handback(actor, requirement_id, run_id):
    from yoke_contracts.api.function_call import FunctionCallRequest, TargetRef
    from yoke_core.domain.handlers.qa_artifact_add import handle_qa_artifact_add

    outcome = handle_qa_artifact_add(FunctionCallRequest(
        function="qa.artifact.add", actor=actor,
        target=TargetRef(kind="qa_requirement", qa_requirement_id=requirement_id),
        payload={
            "run_id": run_id, "artifact_type": "starting_state_restore",
            "content_type": "application/json", "filename": "restore.json",
            "content_base64": base64.b64encode(json.dumps({
                "restored": True, "baseline": "fresh-host",
            }).encode()).decode(),
        },
    ))
    assert outcome.primary_success, outcome.error


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
        test_db, plan_id=case["plan_id"], case_key=case["case_key"],
        host_baseline=None, deployment_run_id=None,
    )
    assert proof["review"]["state"] == "awaiting_walk_review"


def assert_walking_proof(conn, execution):
    from yoke_core.domain.qa_plan_case_proof import _case_result

    case = execution["roster"][0]
    proof = _case_result(
        conn, plan_id=case["plan_id"], case_key=case["case_key"],
        host_baseline=case["host_baseline"], deployment_run_id=None,
    )
    assert execution["state"] == proof["review"]["state"] == "walking"
    assert proof["review"]["capture_runner"] == "agent_mission"
