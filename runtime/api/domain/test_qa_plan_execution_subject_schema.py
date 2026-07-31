"""Permanent coverage for item and deployment-run plan execution subjects."""

from __future__ import annotations

from yoke_core.domain.qa_plan_execution_schema import (
    assert_qa_plan_execution_schema_invariants,
    assert_qa_plan_execution_subject_invariants,
    converge_qa_plan_execution_schema,
    converge_qa_plan_execution_subject_schema,
)


def test_subject_convergence_is_idempotent(test_db) -> None:
    converge_qa_plan_execution_subject_schema(test_db)
    assert_qa_plan_execution_subject_invariants(test_db)
    converge_qa_plan_execution_subject_schema(test_db)
    assert_qa_plan_execution_subject_invariants(test_db)


def test_boot_convergence_expands_exact_legacy_postgres_shape(test_db) -> None:
    test_db.execute("DROP TABLE qa_plan_execution_results")
    test_db.execute("DROP TABLE qa_plan_executions")
    test_db.execute(
        """
        CREATE TABLE qa_plan_executions (
            id TEXT PRIMARY KEY,
            item_id INTEGER NOT NULL,
            transition_id TEXT NOT NULL,
            actor_id TEXT,
            session_id TEXT NOT NULL,
            roster_digest TEXT NOT NULL,
            roster_json TEXT NOT NULL,
            cursor_ordinal INTEGER NOT NULL DEFAULT 0,
            state TEXT NOT NULL CHECK(state IN (
                'active','waiting','completed','aborted','error'
            )),
            machine_lease_id INTEGER,
            created_at TEXT NOT NULL,
            heartbeat_at TEXT NOT NULL,
            completed_at TEXT,
            release_reason TEXT
        )
        """
    )
    test_db.execute(
        "CREATE UNIQUE INDEX idx_qa_plan_executions_active "
        "ON qa_plan_executions(item_id, transition_id) "
        "WHERE state IN ('active','waiting')"
    )
    test_db.execute(
        "INSERT INTO qa_plan_executions("
        "id,item_id,transition_id,session_id,roster_digest,roster_json,"
        "state,created_at,heartbeat_at"
        ") VALUES ("
        "'legacy-execution',1,'implemented','legacy-session','digest','[]',"
        "'active','then','then'"
        ")"
    )

    converge_qa_plan_execution_schema(test_db)
    assert_qa_plan_execution_schema_invariants(test_db)
    assert_qa_plan_execution_subject_invariants(test_db)
    converge_qa_plan_execution_schema(test_db)

    columns = {
        str(row[0]): str(row[1])
        for row in test_db.execute(
            "SELECT column_name,is_nullable FROM information_schema.columns "
            "WHERE table_schema=current_schema() "
            "AND table_name='qa_plan_executions' "
            "AND column_name IN ('item_id','deployment_run_id','transition_id')"
        ).fetchall()
    }
    assert columns == {
        "deployment_run_id": "YES",
        "item_id": "YES",
        "transition_id": "YES",
    }
    checks = {
        str(row[0]): str(row[1])
        for row in test_db.execute(
            "SELECT conname,pg_get_constraintdef(oid) "
            "FROM pg_constraint "
            "WHERE conrelid='qa_plan_executions'::regclass "
            "AND contype='c'"
        ).fetchall()
    }
    assert "qa_plan_executions_subject_check" in checks
    assert all(
        subject in checks["qa_plan_executions_subject_check"]
        for subject in ("item_id", "deployment_run_id", "transition_id")
    )
    assert test_db.execute(
        "SELECT item_id,deployment_run_id,transition_id "
        "FROM qa_plan_executions WHERE id='legacy-execution'"
    ).fetchone() == (1, None, "implemented")
