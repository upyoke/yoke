"""Test-machine readiness facts used by the capability roster."""

from __future__ import annotations

from typing import Any

from yoke_contracts.machine_config.capability_secrets import (
    TEST_MACHINE_CAPABILITY,
)

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _table_exists


def read_test_machine_facts(
    conn: Any,
    project_ids: list[int],
) -> tuple[dict[int, str], set[int], int]:
    """Return verification states, active leases, and Machine method count."""
    if not project_ids:
        return {}, set(), 0
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    placeholders = ", ".join([marker] * len(project_ids))
    verification = {}
    if _table_exists(conn, "test_machine_verifications"):
        verification = {
            int(row["project_id"]): str(row["status"])
            for row in conn.execute(
                "SELECT project_id,status FROM test_machine_verifications "
                f"WHERE project_id IN ({placeholders})",
                tuple(project_ids),
            ).fetchall()
        }
    active = set()
    if _table_exists(conn, "coordination_leases"):
        active = {
            int(row["project_id"])
            for row in conn.execute(
                "SELECT DISTINCT project_id FROM coordination_leases "
                f"WHERE project_id IN ({placeholders}) "
                "AND lease_key LIKE 'QA_HOST:%%' AND released_at IS NULL",
                tuple(project_ids),
            ).fetchall()
        }
    count_row = None
    if _table_exists(conn, "qa_methods"):
        count_row = conn.execute(
            "SELECT COUNT(*) FROM qa_methods "
            f"WHERE required_capability_kind={marker}",
            (TEST_MACHINE_CAPABILITY,),
        ).fetchone()
    return verification, active, int(count_row[0] if count_row else 0)


__all__ = ["read_test_machine_facts"]
