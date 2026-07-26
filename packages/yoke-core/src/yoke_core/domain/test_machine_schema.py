"""Additive verification receipts for composite test-machine capabilities."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.schema_init_apply import execute_schema_script


TEST_MACHINE_VERIFICATION_SQL = """
CREATE TABLE IF NOT EXISTS test_machine_verifications (
    project_id INTEGER PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
    status TEXT NOT NULL
        CHECK(status IN ('configured_unverified','verified','error')),
    checked_at TEXT,
    receipt_json TEXT NOT NULL DEFAULT '{}',
    error_code TEXT,
    updated_at TEXT NOT NULL
)
"""


def ensure_test_machine_schema(conn: Any) -> None:
    """Converge the receipt table without changing capability ownership."""
    execute_schema_script(conn, TEST_MACHINE_VERIFICATION_SQL)
    conn.commit()


__all__ = ["TEST_MACHINE_VERIFICATION_SQL", "ensure_test_machine_schema"]
