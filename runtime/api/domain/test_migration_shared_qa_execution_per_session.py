"""Stage-wide live QA executions re-key from (run, stage) to (run, stage, session)."""

import importlib

import pytest

from yoke_core.domain import db_backend
from yoke_core.domain.migration_serving_version import NEXT_RELEASE

MIGRATION = importlib.import_module(
    "yoke_core.domain.migrations.0088_shared_qa_execution_per_session"
)
INDEX = "idx_qa_plan_executions_deployment_stage_active"


def _install_run_and_stage_key(conn) -> None:
    conn.execute(f'DROP INDEX "{INDEX}"')
    conn.execute(
        f"CREATE UNIQUE INDEX {INDEX} "
        "ON qa_plan_executions(deployment_run_id,deployment_stage) "
        "WHERE deployment_run_id IS NOT NULL AND deployment_stage IS NOT NULL "
        "AND deployment_member_item_id IS NULL "
        "AND state IN ('active','awaiting_agent_review','waiting')"
    )


def _live_stage_row(conn, execution_id: str, session_id: str) -> None:
    conn.execute(
        "INSERT INTO qa_plan_executions(id,deployment_run_id,deployment_stage,"
        "session_id,roster_digest,roster_json,state,created_at,heartbeat_at) "
        "VALUES (%s,'run-rekey','item-qa',%s,'digest','[]','active',"
        "'2026-10-20T00:00:00Z','2026-10-20T00:00:00Z')",
        (execution_id, session_id),
    )


def test_old_key_fails_the_invariant_until_the_entry_rekeys_it(test_db) -> None:
    _install_run_and_stage_key(test_db)
    with pytest.raises(AssertionError, match="wrong keys"):
        MIGRATION.invariants(test_db)
    _live_stage_row(test_db, "first", "session-a")
    MIGRATION.apply(test_db)
    MIGRATION.apply(test_db)
    MIGRATION.invariants(test_db)
    assert MIGRATION.MINIMUM_SERVING_VERSION == NEXT_RELEASE


def test_each_session_holds_one_live_stage_execution(test_db) -> None:
    MIGRATION.apply(test_db)
    _live_stage_row(test_db, "first", "session-a")
    _live_stage_row(test_db, "second", "session-b")
    test_db.execute("SAVEPOINT same_session")
    with pytest.raises(db_backend.integrity_error_types(test_db)):
        _live_stage_row(test_db, "third", "session-a")
    test_db.execute("ROLLBACK TO SAVEPOINT same_session")
    test_db.execute("UPDATE qa_plan_executions SET state='completed' WHERE id='first'")
    _live_stage_row(test_db, "third", "session-a")
