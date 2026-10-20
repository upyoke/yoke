"""Existing machine receipt constraints widen atomically to admit reset debt."""

import importlib

import pytest

MIGRATION = importlib.import_module(
    "yoke_core.domain.migrations.0087_machine_reset_debt_receipts"
)


def legacy_receipts(conn):
    conn.execute("DROP TABLE IF EXISTS test_machine_operation_receipts")
    conn.execute(
        "CREATE TABLE test_machine_operation_receipts ("
        "project_id INTEGER, capability_type TEXT, "
        "operation TEXT CHECK(operation IN ('reset','golden_capture','bridge_diagnose','screenshot')), "
        "receipt_json TEXT)"
    )
    conn.execute(
        "INSERT INTO test_machine_operation_receipts VALUES (1,'test-machine:lab','reset','{}')"
    )


def test_migration_preserves_existing_receipts_and_is_repeatable(test_db):
    legacy_receipts(test_db)
    MIGRATION.apply(test_db)
    MIGRATION.apply(test_db)
    MIGRATION.invariants(test_db)
    assert (
        test_db.execute(
            "SELECT operation FROM test_machine_operation_receipts"
        ).fetchone()[0]
        == "reset"
    )
    test_db.execute(
        "INSERT INTO test_machine_operation_receipts VALUES (1,'test-machine:lab','reset_owed','{}')"
    )
    test_db.execute("SAVEPOINT invalid_operation")
    with pytest.raises(Exception):
        test_db.execute(
            "INSERT INTO test_machine_operation_receipts VALUES (1,'test-machine:lab','unknown','{}')"
        )
    test_db.execute("ROLLBACK TO SAVEPOINT invalid_operation")


def test_migration_rolls_back_with_its_callers_transaction(test_db):
    legacy_receipts(test_db)
    test_db.execute("SAVEPOINT receipt_check")
    MIGRATION.apply(test_db)
    test_db.execute("ROLLBACK TO SAVEPOINT receipt_check")
    with pytest.raises(AssertionError, match="machine_reset_debt_check_missing"):
        MIGRATION.invariants(test_db)
