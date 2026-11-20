"""A parked set-waiter's partial reservations go to the next waiter after a limit.

A plan execution waiting for a host set keeps each host reserved for it while
it waits for the rest (``qa_host_set_turns``). Parking is the normal way to
wait, but a set-waiter whose session is parked, process-exited or ended and has
made no tool call for the machine setting ``qa_host_idle_hold_minutes`` is
*away*: while it still waits on another host, serving it a host only strands
that host. Such a waiter keeps its place in every line, and is skipped when a
host is served (:func:`serving_line`), so each host goes to the next waiter.
Control-plane upkeep hands the reservations it already holds to the next
waiter the same way (:func:`hand_off_idle_waiter_reservations`).

A new running turn after a recorded death or a fresh tool call ends the skip: the next release serves it at its place,
an older-waiter pass returns a younger set's partial reservation to it, and
its resume takes any host that is free.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Iterable, Mapping

from yoke_contracts.timestamps import parse_instant, utc_now
from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.qa_plan_execution_store import marker as _p
from yoke_core.domain.schema_common import _table_exists

_LOG = logging.getLogger(__name__)


def _sessions(conn: Any, session_ids: Iterable[str]) -> dict[str, dict[str, Any]]:
    ids = sorted({str(value) for value in session_ids})
    if not ids:
        return {}
    from yoke_core.domain.qa_host_idle_hold import child_activity_sql

    rows = query_rows(
        conn,
        "SELECT session_id, session_id AS live_row, mode, last_tool_call_at, "
        f"{child_activity_sql(conn, 'harness_sessions')} AS last_child_tool_call_at, "
        "native_process_gone_at, ended_at, terminated_at, turn_posture, turn_posture_at "
        "FROM harness_sessions "
        f"WHERE session_id IN ({','.join([_p(conn)] * len(ids))})",
        tuple(ids),
    )
    return {str(row["session_id"]): dict(row) for row in rows}


def waiter_away(
    wait: Mapping[str, Any], session: Mapping[str, Any] | None, *,
    now: datetime, limit: timedelta,
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


def serving_line(conn: Any, test_machine: str) -> list[dict[str, Any]]:
    """The host's line as a release serves it. Two kinds of wait keep their
    place but are passed over: an away set-waiter still waiting on another
    host, and an execution whose owning run has not opened its QA stage
    (``qa_host_stage_unopened``)."""
    from yoke_core.domain.qa_host_idle_hold import idle_hold_limit
    from yoke_core.domain.qa_host_set_turns import awaits_other_hosts
    from yoke_core.domain.qa_host_stage_unopened import execution_stage_unopened
    from yoke_core.domain.qa_host_turns import host_line

    line = host_line(conn, test_machine)
    if not any(wait["qa_plan_execution_id"] for wait in line):
        return line
    sessions = _sessions(conn, (wait["session_id"] for wait in line))
    now, limit = utc_now(), idle_hold_limit()
    return [
        wait
        for wait in line
        if not (
            waiter_away(wait, sessions.get(str(wait["session_id"])), now=now, limit=limit)
            and awaits_other_hosts(conn, wait)
        )
        and not execution_stage_unopened(conn, wait["qa_plan_execution_id"])
    ]


def hand_off_idle_waiter_reservations(
    conn: Any, *, now: datetime | None = None
) -> list[int]:
    """Control-plane upkeep: pass an away set-waiter's partial reservations on.

    Each wait goes back to ``waiting`` at its own place before its claim is
    released, so the release neither cancels it nor aborts its execution and
    serves the host to the next waiter :func:`serving_line` names.
    """
    from yoke_core.domain.coordination_claims import get_claim, release
    from yoke_core.domain.qa_host_idle_hold import (
        IDLE_HOLD_RESERVATION_REASON,
        idle_hold_limit,
    )
    from yoke_core.domain.qa_host_set_turns import awaits_other_hosts
    from yoke_core.domain.qa_host_turns import lock_host_turn

    if not _table_exists(conn, "qa_test_machine_waits"):
        return []
    current, limit = now or utc_now(), idle_hold_limit()
    rows = query_rows(
        conn,
        "SELECT * FROM qa_test_machine_waits WHERE state='reserved' "
        "AND claim_id IS NOT NULL AND qa_plan_execution_id IS NOT NULL ORDER BY id",
    )
    sessions = _sessions(conn, (row["session_id"] for row in rows))
    conn.commit()
    handed = []
    for row in rows:
        if not waiter_away(row, sessions.get(str(row["session_id"])), now=current, limit=limit):
            continue
        claim = get_claim(conn, int(row["claim_id"]))
        lock_host_turn(conn, claim.target)
        fresh = query_rows(
            conn,
            f"SELECT * FROM qa_test_machine_waits WHERE id={_p(conn)} "
            f"AND state='reserved' AND claim_id={_p(conn)}",
            (str(row["id"]), claim.id),
        )
        session_id = str(row["session_id"])
        session = _sessions(conn, (session_id,)).get(session_id)
        if (
            not fresh
            or not claim.is_active
            or not waiter_away(fresh[0], session, now=current, limit=limit)
            or not awaits_other_hosts(conn, fresh[0])
        ):
            conn.rollback()
            continue
        try:
            conn.execute(
                "UPDATE qa_test_machine_waits SET state='waiting',claim_id=NULL "
                f"WHERE id={_p(conn)}",
                (str(row["id"]),),
            )
            release(conn, claim.id, IDLE_HOLD_RESERVATION_REASON, commit=False)
            conn.commit()
        except Exception:  # noqa: BLE001 - one waiter never blocks the rest
            conn.rollback()
            _LOG.warning(
                "qa_host_idle_waiter_handoff_failed: reservation %s on %s stays "
                "with session %s; the next upkeep pass retries",
                claim.id, claim.target.test_machine, claim.session_id, exc_info=True,
            )
            continue
        handed.append(claim.id)
    return handed


__all__ = ["hand_off_idle_waiter_reservations", "serving_line", "waiter_away"]
