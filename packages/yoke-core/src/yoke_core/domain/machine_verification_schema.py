"""Additive receipts for composite machine-QA capability operations."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.schema_init_apply import execute_schema_script


TEST_MACHINE_VERIFICATION_SQL = """
CREATE TABLE IF NOT EXISTS test_machine_verifications (
    project_id INTEGER NOT NULL,
    capability_type TEXT NOT NULL,
    status TEXT NOT NULL
        CHECK(status IN ('configured_unverified','verified','error')),
    checked_at TEXT,
    receipt_json TEXT NOT NULL DEFAULT '{}',
    error_code TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(project_id, capability_type),
    FOREIGN KEY(project_id, capability_type)
        REFERENCES project_capabilities(project_id, type) ON DELETE CASCADE
)
"""

# The last receipt per machine per operation. Readiness stays the verification
# row's business: a reset leaves a machine fresh rather than unverified, and a
# capture and a diagnosis change nothing about whether the box is controllable.
# Keeping them in their own table is what lets the board show what was last
# done to a machine without any of it moving the machine's availability.
TEST_MACHINE_OPERATION_RECEIPT_SQL = """
CREATE TABLE IF NOT EXISTS test_machine_operation_receipts (
    project_id INTEGER NOT NULL,
    capability_type TEXT NOT NULL,
    operation TEXT NOT NULL
        CHECK(operation IN ('reset','golden_capture','bridge_diagnose')),
    status TEXT NOT NULL CHECK(status IN ('verified','error')),
    performed_at TEXT NOT NULL,
    receipt_json TEXT NOT NULL DEFAULT '{}',
    error_code TEXT,
    lease_id INTEGER,
    contract_digest TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(project_id, capability_type, operation),
    FOREIGN KEY(project_id, capability_type)
        REFERENCES project_capabilities(project_id, type) ON DELETE CASCADE
)
"""


def ensure_test_machine_schema(
    conn: Any,
    *,
    commit: bool = True,
) -> None:
    """Converge receipts, committing unless the caller owns the transaction."""
    execute_schema_script(conn, TEST_MACHINE_VERIFICATION_SQL)
    execute_schema_script(conn, TEST_MACHINE_OPERATION_RECEIPT_SQL)
    if commit:
        conn.commit()


__all__ = [
    "TEST_MACHINE_OPERATION_RECEIPT_SQL",
    "TEST_MACHINE_VERIFICATION_SQL",
    "ensure_test_machine_schema",
]
