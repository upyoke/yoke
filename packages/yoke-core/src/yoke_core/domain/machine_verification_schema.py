"""Additive verification receipts for composite machine-QA capabilities."""

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


def ensure_test_machine_schema(
    conn: Any,
    *,
    commit: bool = True,
) -> None:
    """Converge receipts, committing unless the caller owns the transaction."""
    execute_schema_script(conn, TEST_MACHINE_VERIFICATION_SQL)
    if commit:
        conn.commit()


__all__ = ["TEST_MACHINE_VERIFICATION_SQL", "ensure_test_machine_schema"]
