"""Permit durable machine reset debt without changing existing receipts."""

from yoke_core.domain.migration_serving_version import NEXT_RELEASE
from yoke_core.domain.schema_common import _table_exists

MINIMUM_SERVING_VERSION = NEXT_RELEASE


def apply(conn):
    if not _table_exists(conn, "test_machine_operation_receipts"):
        return
    conn.execute(
        "ALTER TABLE test_machine_operation_receipts DROP CONSTRAINT IF EXISTS "
        "test_machine_operation_receipts_operation_check"
    )
    conn.execute(
        "ALTER TABLE test_machine_operation_receipts ADD CONSTRAINT "
        "test_machine_operation_receipts_operation_check "
        "CHECK(operation IN ('reset','golden_capture','bridge_diagnose','screenshot','reset_owed'))"
    )


def invariants(conn):
    if not _table_exists(conn, "test_machine_operation_receipts"):
        return
    row = conn.execute(
        "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
        "WHERE conrelid='test_machine_operation_receipts'::regclass "
        "AND conname='test_machine_operation_receipts_operation_check'"
    ).fetchone()
    if row is None or "'reset_owed'" not in str(row[0]):
        raise AssertionError(
            "machine_reset_debt_check_missing: rehearse the reset-debt receipt migration"
        )
