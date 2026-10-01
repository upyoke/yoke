"""Postgres constraint cutover preserves receipts and rolls back atomically."""

from __future__ import annotations

import importlib

import pytest


MIGRATION = importlib.import_module(
    "yoke_core.domain.migrations.0051_machine_screenshot_receipts"
)


def legacy_table(conn):
    conn.execute("DROP TABLE IF EXISTS test_machine_operation_receipts")
    conn.execute(
        "CREATE TABLE test_machine_operation_receipts ("
        "project_id INTEGER NOT NULL, capability_type TEXT NOT NULL, "
        "operation TEXT NOT NULL CHECK(operation IN ('reset','golden_capture','bridge_diagnose')), "
        "receipt_json TEXT NOT NULL, PRIMARY KEY(project_id, capability_type, operation))"
    )
    conn.execute(
        "INSERT INTO test_machine_operation_receipts VALUES "
        "(1,'test-machine:lab','reset','{\"checks\":[{\"ok\":true}]}')"
    )


def test_existing_receipt_survives_and_repeat_apply_is_safe(test_db):
    legacy_table(test_db)
    before = [
        tuple(row)
        for row in test_db.execute(
            "SELECT * FROM test_machine_operation_receipts"
        ).fetchall()
    ]
    MIGRATION.apply(test_db)
    MIGRATION.invariants(test_db)
    MIGRATION.apply(test_db)
    MIGRATION.invariants(test_db)
    assert [
        tuple(row)
        for row in test_db.execute(
            "SELECT * FROM test_machine_operation_receipts"
        ).fetchall()
    ] == before
    test_db.execute(
        "INSERT INTO test_machine_operation_receipts VALUES (1,'test-machine:lab','screenshot','{}')"
    )
    test_db.execute("SAVEPOINT refused_operation")
    with pytest.raises(Exception):
        test_db.execute(
            "INSERT INTO test_machine_operation_receipts VALUES (1,'test-machine:lab','unknown','{}')"
        )
    test_db.execute("ROLLBACK TO SAVEPOINT refused_operation")


def test_constraint_replacement_rolls_back_with_transaction(test_db):
    legacy_table(test_db)
    test_db.execute("SAVEPOINT receipt_change")
    MIGRATION.apply(test_db)
    test_db.execute("ROLLBACK TO SAVEPOINT receipt_change")
    with pytest.raises(
        AssertionError, match="machine_screenshot_receipt_check_missing"
    ):
        MIGRATION.invariants(test_db)
    assert (
        test_db.execute(
            "SELECT operation FROM test_machine_operation_receipts"
        ).fetchone()[0]
        == "reset"
    )
