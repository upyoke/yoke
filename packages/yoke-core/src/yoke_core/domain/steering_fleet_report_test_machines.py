"""Test-host OS facts in a project fleet report, separate from launch capacity."""

from __future__ import annotations
import json
from typing import Any, NamedTuple
from yoke_core.domain.schema_common import _table_exists


class ResetDebt(NamedTuple):
    test_machine: str
    recovery: str | None
    execution_id: str | None


class IdleHostHold(NamedTuple):
    """A host a parked, exited or ended session holds; rides with reset debts.

    It names when upkeep returns the host to the line (``qa_host_idle_hold``);
    its recovery is the steering release, so the report alarms before then.
    """

    test_machine: str
    recovery: str
    idle_session: str
    idle_state: str
    idle_since: str
    returns_at: str


class QueuedWalk(NamedTuple):
    """One waiter in the Test Machine queue; rides with reset debts.

    ``test_machine`` names what it waits for: one machine, ``any of`` the
    machines that can serve it, or ``all of`` a simultaneous host set.
    """

    test_machine: str
    place: str
    session_id: str
    execution_id: str | None
    queued_at: str
    recovery: None = None


def read_queue(conn: Any) -> list[QueuedWalk]:
    """The one Test Machine queue, oldest waiter first."""
    from yoke_core.domain.qa_host_queue import (
        position_text,
        queue_entries,
        waits_for_text,
    )

    if not _table_exists(conn, "qa_test_machine_waits"):
        return []
    return [
        QueuedWalk(
            waits_for_text(entry),
            position_text(entry["places"]),
            str(entry["session_id"]),
            entry["execution_id"],
            str(entry["queued_at"]),
        )
        for entry in queue_entries(conn)
    ]


def _holding_execution(conn: Any, test_machine: str) -> str | None:
    from yoke_core.domain.coordination_claims import active_claim
    from yoke_core.domain.machine_qa_capability import host_claim_target
    from yoke_core.domain.qa_plan_execution_schema import LIVE_PLAN_EXECUTION_SQL
    from yoke_core.domain.qa_plan_execution_store import marker
    from yoke_core.domain.qa_case_host_custody import claim_execution_id

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
        f"AND (test_machine_lease_id={p} OR id={p}) LIMIT 1",
        (lease.id, claim_execution_id(lease.reason)),
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


def _idle_holds(conn: Any, names: set[str]) -> list[IdleHostHold]:
    """Consumed host leases whose holder is parked, exited or ended.

    Recent subagent activity or a live execution heartbeat keeps the hold active.
    """
    from yoke_contracts.timestamps import format_instant, utc_now
    from yoke_core.domain import qa_host_idle_hold as idle

    if not _table_exists(conn, "qa_test_machine_waits"):
        return []
    now, limit, holds = utc_now(), idle.idle_hold_limit(), []
    for row in idle.held_rows(conn):
        away = idle.holder_away(row, now=now, limit=limit)
        machine = str(row["test_machine"])
        if not away or machine not in names:
            continue
        since = idle.idle_since(row)
        holds.append(
            IdleHostHold(
                machine,
                f"yoke coordination-claim release --key QA_HOST:{machine} "
                f"--claim-id {row['id']} --holder-session-id {row['session_id']} "
                '--reason "<why>"',
                idle_session=str(row["session_id"]),
                idle_state=away,
                idle_since=format_instant(since),
                returns_at=format_instant(since + limit),
            )
        )
    return holds


def read_reset_debts(
    conn, project_id
) -> tuple[ResetDebt | IdleHostHold | QueuedWalk, ...]:
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
    return (*debts, *read_queue(conn))


def reset_debt_lines(rows):
    return [
        f"Test Machine queue: session {row.session_id}"
        + (f" (execution {row.execution_id})" if row.execution_id else "")
        + f" waits for {row.test_machine} ({row.place}) since {row.queued_at}"
        if isinstance(row, QueuedWalk)
        else f"Test Machine {row.test_machine}: ALARM held by {row.idle_state} session "
        f"{row.idle_session}, silent since {row.idle_since}; upkeep returns it to "
        f"the queue at {row.returns_at}. If Yoke should have handled this automatically, "
        "root-cause it with a subagent and file feedback first; a nudge is a workaround. "
        f"workaround=`{row.recovery}`"
        if isinstance(row, IdleHostHold)
        else f"Test Machine {row.test_machine}: reset owed after {row.execution_id}"
        if row.execution_id
        else f"Test Machine {row.test_machine}: machine_needs_repair; run `{row.recovery}`"
        for row in rows
    ]
