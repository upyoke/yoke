"""The Doctor catalog follows every current schema convergence owner."""

from __future__ import annotations

import pytest

from yoke_core.domain import db_backend, environment_bootstrap
from yoke_core.domain.schema_expected_catalog import (
    parse_expected_schema,
)
from yoke_core.engines.doctor_hc_db_project_schema import hc_schema_drift
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector
from runtime.api.fixtures import pg_testdb


def test_expected_catalog_includes_ordered_migration_ledger() -> None:
    expected = parse_expected_schema()

    assert expected["applied_migrations"] == {
        "migration_name": "TEXT",
        "applied_at": "TEXT",
        "applied_by": "TEXT",
        "minimum_serving_version": "TEXT",
        "content_sha256": "TEXT",
    }
    assert expected["doctor_runs"]["ran_at"] == "TEXT"
    assert expected["doctor_runs"]["results"] == "TEXT"
    assert expected["migration_content_adoptions"]["source_sha256"] == "TEXT"


def test_expected_catalog_includes_additive_workflow_and_lane_columns() -> None:
    expected = parse_expected_schema()

    assert expected["decision_requests"] == {
        "id": "INTEGER",
        "kind": "TEXT",
        "subject_type": "TEXT",
        "subject_key": "TEXT",
        "subject_context": "TEXT",
        "project_id": "INTEGER",
        "org_id": "INTEGER",
        "originator_actor_id": "INTEGER",
        "status": "TEXT",
        "resolution_action": "TEXT",
        "resolution_actor_id": "INTEGER",
        "resolution_note": "TEXT",
        "resolved_at": "TEXT",
        "withdrawal_reason": "TEXT",
        "withdrawn_at": "TEXT",
        "consumed_at": "TEXT",
        "consumed_from_stage": "TEXT",
        "consumed_to_stage": "TEXT",
        "consumed_workflow_version_id": "INTEGER",
        "created_at": "TEXT",
    }
    assert expected["item_worktrees"]["commit_sha"] == "TEXT"
    assert expected["workflow_versions"]["derived_from_canon_version"] == "INTEGER"


def test_bootstrapped_schema_matches_doctor_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = pg_testdb.create_test_database()
    try:
        monkeypatch.setenv(
            db_backend.PG_DSN_ENV,
            pg_testdb.dsn_for_test_database(database),
        )
        environment_bootstrap.run_init_chain(lambda _line: None)
        conn = pg_testdb.connect_test_database(database)
        try:
            rec = RecordCollector()
            hc_schema_drift(conn, DoctorArgs(project="yoke"), rec)
            assert len(rec.results) == 1
            assert rec.results[0].result == "PASS", rec.results[0].detail
        finally:
            conn.close()
    finally:
        pg_testdb.drop_test_database(database)
