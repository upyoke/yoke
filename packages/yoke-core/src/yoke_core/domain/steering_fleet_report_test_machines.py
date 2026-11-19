"""Test-host OS facts in a project fleet report, separate from launch capacity."""

from __future__ import annotations
import json
from typing import Any, NamedTuple
from yoke_core.domain.schema_common import _table_exists


class ResetDebt(NamedTuple):
    """A Test Machine finding: a reset owed, or a host an away session holds.

    An idle hold names the parked, exited or ended holder and when upkeep
    returns the host to the line (``qa_host_idle_hold``); its recovery is the
    steering release, so the report alarms before that limit.
    """

    test_machine: str
    recovery: str | None
    execution_id: str | None
    idle_session: str | None = None
    idle_state: str | None = None
    idle_since: str | None = None
    returns_at: str | None = None


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
    if not _table_exists(conn, "test_machines"):
        return ()
    rows = conn.execute(
        "SELECT name, settings FROM test_machines ORDER BY name",
    ).fetchall()
    result = []
    for row in rows:
        settings = json.loads(str(row[1] or "{}"))
        result.append(
            (
                str(row[0]),
                str(settings.get("os") or "requires next-release serving build")
                + (
                    f" · {settings.get('cloud_provider', 'aws')}"
                    if settings.get("cloud_instance_id")
                    else ""
                ),
            )
        )
    return tuple(result)


def test_machine_lines(rows: tuple[tuple[str, str], ...]) -> list[str]:
    if not rows:
        return []
    return ["Test Machines: " + "; ".join(f"{name} (OS: {os})" for name, os in rows)]


def _idle_holds(conn: Any, names: set[str]) -> list[ResetDebt]:
    """Consumed host leases whose holder is parked, exited or ended."""
    from yoke_contracts.timestamps import format_instant
    from yoke_core.domain import qa_host_idle_hold as idle

    if not _table_exists(conn, "qa_test_machine_waits"):
        return []
    limit, holds = idle.idle_hold_limit(), []
    for row in idle.held_rows(conn):
        away = idle.holder_away(row)
        machine = str(row["test_machine"])
        if not away or machine not in names:
            continue
        since = idle.idle_since(row)
        holds.append(
            ResetDebt(
                machine,
                f"yoke coordination-claim release --key QA_HOST:{machine} "
                f"--claim-id {row['id']} --holder-session-id {row['session_id']} "
                '--reason "<why>"',
                None,
                idle_session=str(row["session_id"]),
                idle_state=away,
                idle_since=format_instant(since),
                returns_at=format_instant(since + limit),
            )
        )
    return holds


def read_reset_debts(conn, project_id) -> tuple[ResetDebt, ...]:
    from yoke_core.domain.machine_reset_debt import reset_command, reset_owed

    if not _table_exists(conn, "test_machine_operation_receipts"):
        return ()
    names = {name for name, _ in read_test_machines(conn, project_id)}
    debts = _idle_holds(conn, names)
    for name, _ in read_test_machines(conn, project_id):
        if (baseline := reset_owed(conn, name)) is None:
            continue
        execution_id = _holding_execution(conn, name)
        debts.append(
            ResetDebt(
                name,
                None if execution_id else reset_command(name, baseline),
                execution_id,
            )
        )
    return tuple(debts)


def reset_debt_lines(rows):
    return [
        f"Test Machine {row.test_machine}: ALARM held by {row.idle_state} session "
        f"{row.idle_session}, silent since {row.idle_since}; upkeep returns it to "
        f"the line at {row.returns_at}, or release it now: `{row.recovery}`"
        if row.idle_session
        else f"Test Machine {row.test_machine}: reset owed after {row.execution_id}"
        if row.execution_id
        else f"Test Machine {row.test_machine}: machine_needs_repair; run `{row.recovery}`"
        for row in rows
    ]
