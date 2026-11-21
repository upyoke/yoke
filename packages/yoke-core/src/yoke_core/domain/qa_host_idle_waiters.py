"""Upkeep returns partial reservations when a host set cannot take its turn.

A plan execution can reserve its set from the front of every host line
(``qa_host_set_turns``). A set-waiter whose session is parked, process-exited or ended and has
made no tool call for the machine setting ``qa_host_idle_hold_minutes`` is
*away*: while it still waits on another host, serving it a host only strands
that host. Such a waiter keeps its place in the queue, and is skipped when a
host is served (:func:`serving_waiters`), so each host goes to the next waiter.
Control-plane upkeep hands the reservations it already holds to the next
waiter the same way (:func:`hand_off_idle_waiter_reservations`).

A new running turn or tool call ends the skip. The next release serves the
waiter at its place and upkeep checks hosts that are already free.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Iterable, Mapping

from yoke_contracts.timestamps import parse_instant, utc_now
from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.qa_plan_execution_store import marker as _p
from yoke_core.domain.schema_common import _table_exists


def _sessions(conn: Any, session_ids: Iterable[str]) -> dict[str, dict[str, Any]]:
    ids = sorted({str(value) for value in session_ids})
    if not ids:
        return {}
    rows = query_rows(
        conn,
        "SELECT session_id, session_id AS live_row, mode, last_tool_call_at, "
        "last_child_tool_call_at, "
        "native_process_gone_at, ended_at, terminated_at, turn_posture, turn_posture_at "
        "FROM harness_sessions "
        f"WHERE session_id IN ({','.join([_p(conn)] * len(ids))})",
        tuple(ids),
    )
    return {str(row["session_id"]): dict(row) for row in rows}


def waiter_away(
    wait: Mapping[str, Any],
    session: Mapping[str, Any] | None,
    *,
    now: datetime,
    limit: timedelta,
) -> bool:
    """The wait's session is parked or exited, and neither it nor its subagent
    made a tool call within *limit*."""
    from yoke_core.domain.qa_host_idle_hold import holder_away

    if not wait.get("qa_plan_execution_id"):
        return False
    row = dict(session or {})
    if not holder_away(row, now=now, limit=limit):
        return False
    last = row.get("last_tool_call_at") or wait["queued_at"]
    return now - parse_instant(last) >= limit


def serving_waiters(conn: Any, test_machine: str) -> list[dict[str, Any]]:
    """The waiters a release of *test_machine* serves, oldest first.

    Two kinds of wait keep their place but are passed over: an away set-waiter still waiting on another
    host, and an execution whose owning run has not opened its QA stage
    (``qa_host_stage_unopened``)."""
    from yoke_core.domain.qa_host_idle_hold import idle_hold_limit
    from yoke_core.domain.qa_host_set_turns import awaits_other_hosts
    from yoke_core.domain.qa_host_stage_unopened import execution_stage_unopened
    from yoke_core.domain.qa_host_turns import machine_waiters

    line = machine_waiters(conn, test_machine)
    if not any(wait["qa_plan_execution_id"] for wait in line):
        return line
    sessions = _sessions(conn, (wait["session_id"] for wait in line))
    now, limit = utc_now(), idle_hold_limit()
    return [
        wait
        for wait in line
        if not (
            waiter_away(
                wait, sessions.get(str(wait["session_id"])), now=now, limit=limit
            )
            and awaits_other_hosts(conn, wait)
        )
        and not execution_stage_unopened(conn, wait["qa_plan_execution_id"])
    ]


def returnable_reservations(
    conn: Any, waits: Iterable[Mapping[str, Any]]
) -> list[Mapping[str, Any]]:
    """Borrowed turns stay in custody while a host operation is running."""
    from yoke_core.domain.coordination_claims import get_claim
    from yoke_core.domain.qa_host_turn_borrow import turn_in_operation

    return [
        wait
        for wait in waits
        if wait["state"] == "reserved"
        and wait["claim_id"] is not None
        and not turn_in_operation(get_claim(conn, int(wait["claim_id"])))
    ]


def recheck_host_sets(conn: Any, machines: Iterable[str]) -> None:
    """A change to a line can invalidate a reservation on another host."""
    from yoke_core.domain.coordination_claims import get_claim
    from yoke_core.domain.qa_host_queue import machine_waiters
    from yoke_core.domain.qa_host_set_turns import execution_waits, pass_blocked_set_reservations

    executions = {
        row["qa_plan_execution_id"]
        for machine in machines
        for row in machine_waiters(conn, machine)
        if row["qa_plan_execution_id"] and not row["need_id"]
    }
    for execution in sorted(executions):
        for wait in execution_waits(conn, execution):
            if wait["state"] == "reserved":
                pass_blocked_set_reservations(conn, get_claim(conn, int(wait["claim_id"])))
                break


def hand_off_idle_waiter_reservations(
    conn: Any, *, now: datetime | None = None
) -> list[int]:
    """Return blocked or away partial sets, then serve free hosts."""
    from yoke_core.domain.db_savepoint import savepoint
    from yoke_core.domain.qa_host_idle_hold import (
        IDLE_HOLD_RESERVATION_REASON,
        idle_hold_limit,
    )
    from yoke_core.domain.qa_host_queue import lock_host_queue, queue_waits
    from yoke_core.domain.qa_host_set_turns import (
        HOST_TURN_PASSED_REASON,
        awaits_other_hosts,
        execution_waits,
        return_reservations,
        set_at_front,
    )
    from yoke_core.domain.qa_host_turns import reserve_host_turn
    from yoke_core.domain.work_claim_targets import make_qa_admission_target

    if not _table_exists(conn, "qa_test_machine_waits"):
        return []
    current, limit = now or utc_now(), idle_hold_limit()
    lock_host_queue(conn)
    rows = query_rows(
        conn,
        "SELECT DISTINCT qa_plan_execution_id FROM qa_test_machine_waits "
        "WHERE state='reserved' AND qa_plan_execution_id IS NOT NULL "
        "ORDER BY qa_plan_execution_id",
    )
    handed = []
    with savepoint(conn, "qa_host_queue_upkeep", owns=True):
        for row in rows:
            waits = execution_waits(conn, row["qa_plan_execution_id"])
            reserved = returnable_reservations(conn, waits)
            if not reserved or not awaits_other_hosts(conn, reserved[0]):
                continue
            first = reserved[0]
            session_id = str(first["session_id"])
            session = _sessions(conn, [session_id]).get(session_id)
            away = waiter_away(first, session, now=current, limit=limit)
            if away or not set_at_front(conn, first):
                reason = (
                    IDLE_HOLD_RESERVATION_REASON if away else HOST_TURN_PASSED_REASON
                )
                return_reservations(conn, reserved, reason)
                handed.extend(int(wait["claim_id"]) for wait in reserved)
        for machine in sorted({str(row["test_machine"]) for row in queue_waits(conn)}):
            reserve_host_turn(conn, make_qa_admission_target(machine))
        conn.commit()
    return handed
