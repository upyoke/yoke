"""Governed migration coverage for deployment-run plan executions."""

from __future__ import annotations

import json
from pathlib import Path

from yoke_core.domain.migration_apply_manifest import validate_manifest_payload
from yoke_core.domain.migration_source_digest import migration_source_digest
from yoke_core.domain.migrations.qa_plan_execution_deployment_subject import (
    MIGRATION_NAME,
    apply,
    invariants,
)
from yoke_core.domain.qa_plan_execution_schema import (
    assert_qa_plan_execution_schema_invariants,
    converge_qa_plan_execution_schema,
)


_ROOT = Path(__file__).resolve().parents[4]
_MANIFEST = Path(__file__).with_name(
    "qa_plan_execution_deployment_subject.migration.json"
)


def test_governed_manifest_is_valid_and_source_bound() -> None:
    payload = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    validate_manifest_payload(payload)
    source = payload["module_sources"][MIGRATION_NAME]
    assert migration_source_digest(_ROOT / source["path"]) == source["sha256"]


def test_apply_expands_item_execution_schema_idempotently(test_db) -> None:
    apply(test_db)
    invariants(test_db)
    apply(test_db)
    invariants(test_db)


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
    invariants(test_db)
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
    indexes = {
        str(row[0])
        for row in test_db.execute(
            "SELECT indexname FROM pg_indexes "
            "WHERE schemaname=current_schema() "
            "AND tablename IN ('qa_plan_executions','qa_plan_execution_results')"
        ).fetchall()
    }
    assert {
        "idx_qa_plan_executions_active",
        "idx_qa_plan_executions_deployment_active",
        "idx_qa_plan_execution_results_requirement",
    } <= indexes
    assert (
        test_db.execute(
            "SELECT item_id,deployment_run_id,transition_id "
            "FROM qa_plan_executions WHERE id='legacy-execution'"
        ).fetchone()
        == (1, None, "implemented")
    )
