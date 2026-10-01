"""Permit screenshot receipts without changing any existing machine evidence."""

from __future__ import annotations

from yoke_core.domain.db_backend import connection_is_postgres
from yoke_core.domain.migration_serving_version import NEXT_RELEASE
from yoke_core.domain.schema_common import _table_exists


MINIMUM_SERVING_VERSION = NEXT_RELEASE


def apply(conn) -> None:
    """Replace only the operation check inside the boot owner's transaction."""
    if not _table_exists(conn, "test_machine_operation_receipts"):
        return
    if not connection_is_postgres(conn):
        raise RuntimeError(
            "machine screenshot receipt migration requires Postgres authority"
        )
    conn.execute(
        "ALTER TABLE test_machine_operation_receipts DROP CONSTRAINT IF EXISTS "
        "test_machine_operation_receipts_operation_check"
    )
    # This immutable history entry records the operation vocabulary at authoring.
    conn.execute(
        "ALTER TABLE test_machine_operation_receipts ADD CONSTRAINT "
        "test_machine_operation_receipts_operation_check "
        "CHECK(operation IN ('reset','golden_capture','bridge_diagnose','screenshot'))"
    )


def invariants(conn) -> None:
    """Require the widened check; existing receipt rows remain untouched."""
    if not _table_exists(conn, "test_machine_operation_receipts"):
        return
    row = conn.execute(
        "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
        "WHERE conrelid='test_machine_operation_receipts'::regclass "
        "AND conname='test_machine_operation_receipts_operation_check'"
    ).fetchone()
    if row is None or "'screenshot'" not in str(row[0]):
        raise AssertionError(
            "machine_screenshot_receipt_check_missing: rehearse the receipt migration"
        )
