"""Test-host OS facts in a project fleet report, separate from launch capacity."""

from __future__ import annotations
import json
from typing import Any, NamedTuple
from yoke_core.domain.schema_common import _table_exists


class ResetDebt(NamedTuple):
    test_machine: str
    recovery: str | None
    execution_id: str | None


def _holding_execution(conn: Any, test_machine: str) -> str | None:
    from yoke_core.domain.coordination_claims import active_claim
    from yoke_core.domain.machine_qa_capability import host_claim_target
    from yoke_core.domain.qa_plan_execution_schema import LIVE_PLAN_EXECUTION_SQL
    from yoke_core.domain.qa_plan_execution_store import marker
    from yoke_core.domain.qa_plan_host_leases import HOST_SET_REASON

    if not _table_exists(conn, "work_claims") or not _table_exists(
        conn, "qa_plan_executions"
    ):
        return None
    lease = active_claim(conn, host_claim_target(test_machine))
    if lease is None:
        return None
    p = marker(conn)
    row = conn.execute(
        f"SELECT id FROM qa_plan_executions WHERE state IN ({LIVE_PLAN_EXECUTION_SQL}) "
        f"AND (test_machine_lease_id={p} OR {p}={p} || id) LIMIT 1",
        (lease.id, lease.reason or "", HOST_SET_REASON),
    ).fetchone()
    return str(row[0]) if row else None


def read_test_machines(conn: Any, project_id: int) -> tuple[tuple[str, str], ...]:
    if not _table_exists(conn, "project_capabilities"):
        return ()
    rows = conn.execute(
        "SELECT type, settings FROM project_capabilities WHERE project_id = %s "
        "AND type LIKE %s ORDER BY type",
        (project_id, "test-machine:%"),
    ).fetchall()
    result = []
    for row in rows:
        settings = json.loads(str(row[1] or "{}"))
        result.append(
            (
                str(row[0]).split(":", 1)[1],
                str(settings.get("os") or "requires next-release serving build"),
            )
        )
    return tuple(result)


def test_machine_lines(rows: tuple[tuple[str, str], ...]) -> list[str]:
    if not rows:
        return []
    return ["Test Machines: " + "; ".join(f"{name} (OS: {os})" for name, os in rows)]


def read_reset_debts(conn, project_id) -> tuple[ResetDebt, ...]:
    from yoke_core.domain.machine_reset_debt import reset_command, reset_owed

    if not _table_exists(conn, "test_machine_operation_receipts"):
        return ()
    debts = []
    for name, _ in read_test_machines(conn, project_id):
        if (baseline := reset_owed(conn, name)) is None:
            continue
        execution_id = _holding_execution(conn, name)
        debts.append(
            ResetDebt(
                name,
                None if execution_id else reset_command(project_id, name, baseline),
                execution_id,
            )
        )
    return tuple(debts)


def reset_debt_lines(rows):
    return [
        f"Test Machine {row.test_machine}: reset owed after {row.execution_id}"
        if row.execution_id
        else f"Test Machine {row.test_machine}: machine_needs_repair; run `{row.recovery}`"
        for row in rows
    ]
