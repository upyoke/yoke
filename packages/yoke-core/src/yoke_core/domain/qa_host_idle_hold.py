"""A QA host held by a parked or exited session returns to the line after a limit.

A walk in ``awaiting_walk_review`` keeps its primary lease on purpose
(``qa_plan_execution_reconcile_hosts.held_leases``), work claims exempt a
session from every stale sweep, and a host lease has no expiry of its own. A
session that parks on a human gate, or whose process exits, mid-walk therefore
held its host, and any host set queued behind it held partial reservations on
its other hosts, until someone released them by hand.

Control-plane upkeep now ends that hold. A held (consumed) ``QA_HOST:<machine>``
lease whose session is parked, process-exited or ended, and has made no tool
call and no recorded host operation on that lease for the machine setting
:data:`IDLE_HOLD_SETTING`, is released through the manual release path
(``qa_host_manual_release``): the reset the next holder owes is recorded and the
owning walk is aborted with a reason naming the ``yoke qa plan run`` that starts
it again. First, every unconsumed reservation held by an execution still waiting
on that host returns to ``waiting`` at the execution's own place and its claim is
released, so each of those hosts serves its line. Each release reserves the host
for its line's oldest waiter and wakes that session.

A subagent's tool calls count as the holder's activity: a parent that parks or
exits while its subagent walks the host is working, so the newest of the
parent's own call, its subagent's call (``last_child_tool_call_at``,
``session_child_activity``) and the lease's host operations sets the idle clock,
and child activity inside the limit keeps the holder from reading as away.

Claim heartbeats never measure idleness here: watcher pulses refresh them while
a parked session does nothing on the host. An away set-waiter's own unconsumed
reservations go to the next waiter instead (``qa_host_idle_waiters``);
hold-overs keep their own expiry (``qa_host_holdover``).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Iterable

from yoke_contracts.timestamps import format_instant, parse_instant, utc_now
from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.qa_plan_execution_store import marker as _p
from yoke_core.domain.schema_common import _table_exists

_LOG = logging.getLogger(__name__)

#: Machine setting: minutes a parked or exited holder may sit on a host.
IDLE_HOLD_SETTING = "qa_host_idle_hold_minutes"
#: Release code of a host lease returned to the line by this module.
IDLE_HOLD_RELEASED_REASON = "qa_host_idle_hold_expired"
#: Release code of a waiting set's reservation returned with it.
IDLE_HOLD_RESERVATION_REASON = "qa-host-turn-returned-idle-holder"

_HELD = (
    "wc.released_at IS NULL AND wc.target_kind='qa_admission' AND NOT EXISTS "
    "(SELECT 1 FROM qa_test_machine_waits w WHERE w.claim_id=wc.id "
    "AND w.state='reserved')"
)


def idle_hold_limit() -> timedelta:
    """The configured idle hold, read from this machine's settings."""
    from yoke_core.domain.runtime_settings import get_int

    return timedelta(minutes=get_int(IDLE_HOLD_SETTING))


def held_qa_hosts(conn: Any, session_ids: Iterable[str]) -> dict[str, list[str]]:
    """Test Machines each session holds a consumed QA host lease on.

    Unconsumed reservations and hold-overs are turns, not hosts in use, so a
    session waiting in line holds nothing here.
    """
    ids = sorted({str(value) for value in session_ids})
    if not ids or not _table_exists(conn, "qa_test_machine_waits"):
        return {}
    from yoke_core.domain.schema_work_claim_sql import scope_text_sql

    p = _p(conn)
    machine = scope_text_sql(conn, "wc.scope", "test_machine")
    rows = query_rows(
        conn,
        f"SELECT wc.session_id, {machine} AS test_machine FROM work_claims wc "
        f"WHERE {_HELD} AND wc.session_id IN ({','.join([p] * len(ids))}) "
        "ORDER BY test_machine",
        tuple(ids),
    )
    held: dict[str, list[str]] = {}
    for row in rows:
        held.setdefault(str(row["session_id"]), []).append(str(row["test_machine"]))
    return held


def held_qa_hosts_sql(conn: Any, session_expr: str) -> str:
    """A correlated subquery: the comma-joined hosts *session_expr* holds.

    For reads pinned to one statement, such as the steering report's holders;
    :func:`held_qa_hosts_csv` splits its value.
    """
    from yoke_core.domain.schema_connection import connection_is_postgres
    from yoke_core.domain.schema_work_claim_sql import scope_text_sql

    machine = scope_text_sql(conn, "wc.scope", "test_machine")
    joined = (
        f"string_agg({machine}, ',' ORDER BY {machine})"
        if connection_is_postgres(conn)
        else f"group_concat({machine}, ',')"
    )
    return (
        f"(SELECT {joined} FROM work_claims wc WHERE {_HELD} "
        f"AND wc.session_id={session_expr})"
    )


def held_qa_hosts_csv(value: Any) -> list[str]:
    """The hosts a :func:`held_qa_hosts_sql` column names, in order."""
    return sorted(part for part in str(value or "").split(",") if part)


def held_rows(conn: Any) -> list[dict[str, Any]]:
    """Every consumed host lease with its holder's activity facts."""
    from yoke_core.domain.schema_work_claim_sql import scope_text_sql

    machine = scope_text_sql(conn, "wc.scope", "test_machine")
    operation = (
        "(SELECT MAX(r.performed_at) FROM test_machine_operation_receipts r "
        "WHERE r.lease_id=wc.id)"
        if _table_exists(conn, "test_machine_operation_receipts")
        else "NULL"
    )
    return query_rows(
        conn,
        f"SELECT wc.id, wc.session_id, wc.claimed_at, {machine} AS test_machine, "
        "hs.session_id AS live_row, "
        "hs.mode, hs.last_tool_call_at, hs.native_process_gone_at, hs.ended_at, "
        f"hs.terminated_at, {child_activity_sql(conn, 'hs')} AS last_child_tool_call_at, "
        f"{operation} AS host_operation_at "
        "FROM work_claims wc "
        "LEFT JOIN harness_sessions hs ON hs.session_id=wc.session_id "
        f"WHERE {_HELD} ORDER BY wc.id",
    )


def child_activity_sql(conn: Any, alias: str) -> str:
    """*alias*'s subagent-call stamp, or NULL where the column has not converged."""
    from yoke_core.domain.schema_common import _get_columns

    if "last_child_tool_call_at" in _get_columns(conn, "harness_sessions"):
        return f"{alias}.last_child_tool_call_at"
    return "NULL"


def holder_away(row: dict[str, Any], *, now: datetime, limit: timedelta) -> str | None:
    """Why the holder cannot use its host now: parked, exited, or ended.

    A holder whose subagent made a tool call within *limit* of *now* is
    working, whatever its own posture, so it is not away.
    """
    from yoke_core.domain.session_mode import session_is_parked
    from yoke_core.domain.session_state import session_presence

    if row.get("live_row") is None:
        return "ended"
    child = row.get("last_child_tool_call_at")
    if child is not None and now - parse_instant(child) < limit:
        return None
    presence = session_presence(row)
    if presence != "present":
        return "exited" if presence == "gone" else "ended"
    return "parked" if session_is_parked(row.get("mode")) else None


def idle_since(row: dict[str, Any]) -> datetime:
    """The holder's or its subagent's last tool call, or a host operation on this lease."""
    stamps = (
        row.get(k)
        for k in (
            "claimed_at", "last_tool_call_at", "last_child_tool_call_at",
            "host_operation_at",
        )
    )
    return max(parse_instant(stamp) for stamp in stamps if stamp is not None)


def _waiting_executions(conn: Any, test_machine: str) -> list[str]:
    rows = query_rows(
        conn,
        "SELECT DISTINCT qa_plan_execution_id FROM qa_test_machine_waits "
        f"WHERE test_machine={_p(conn)} AND state='waiting' "
        "AND qa_plan_execution_id IS NOT NULL ORDER BY qa_plan_execution_id",
        (test_machine,),
    )
    return [str(row["qa_plan_execution_id"]) for row in rows]


def _set_reservations(conn: Any, execution_ids: list[str]) -> list[dict[str, Any]]:
    if not execution_ids:
        return []
    p = _p(conn)
    return query_rows(
        conn,
        "SELECT id, claim_id, test_machine FROM qa_test_machine_waits "
        f"WHERE qa_plan_execution_id IN ({','.join([p] * len(execution_ids))}) "
        "AND state='reserved' AND claim_id IS NOT NULL ORDER BY test_machine",
        tuple(execution_ids),
    )


def return_waiting_set_reservations(conn: Any, test_machine: str) -> list[int]:
    """Return every reservation of a set waiting on *test_machine* to its line.

    Each wait goes back to ``waiting`` at its own ``queued_at``, so the
    execution keeps its place; the release then serves that host's line,
    which reserves it again for the execution when it is still the oldest.
    """
    from yoke_core.domain.coordination_claims import release

    returned = []
    for row in _set_reservations(conn, _waiting_executions(conn, test_machine)):
        conn.execute(
            "UPDATE qa_test_machine_waits SET state='waiting',claim_id=NULL "
            f"WHERE id={_p(conn)} AND state='reserved'",
            (str(row["id"]),),
        )
        release(conn, int(row["claim_id"]), IDLE_HOLD_RESERVATION_REASON, commit=False)
        returned.append(int(row["claim_id"]))
    return returned


def _release_reason(conn: Any, claim: Any, row: dict, away: str, limit: timedelta) -> str:
    from yoke_core.domain.qa_host_turn_release import rerun_command
    from yoke_core.domain.qa_plan_execution_schema import LIVE_PLAN_EXECUTION_SQL
    from yoke_core.domain.qa_plan_host_leases import HOST_SET_REASON

    reason = (
        f"{IDLE_HOLD_RELEASED_REASON}: QA host {claim.target.test_machine} lease "
        f"{claim.id} was held by {away} session {claim.session_id} with no tool "
        f"call, subagent call or host operation since "
        f"{format_instant(idle_since(row))}, past "
        f"the {int(limit.total_seconds() // 60)}-minute {IDLE_HOLD_SETTING} "
        "limit; the reset the next holder owes is recorded"
    )
    companion = str(claim.reason or "")
    companion = companion[len(HOST_SET_REASON):] if companion.startswith(HOST_SET_REASON) else ""
    executions = query_rows(
        conn,
        f"SELECT * FROM qa_plan_executions WHERE state IN ({LIVE_PLAN_EXECUTION_SQL}) "
        f"AND (test_machine_lease_id={_p(conn)} OR CAST(id AS TEXT)={_p(conn)}) "
        "ORDER BY id LIMIT 1",
        (claim.id, companion),
    )
    if executions:
        reason += f"; start the walk again with `{rerun_command(conn, executions[0])}`"
    return reason


def release_idle_host_holds(conn: Any, *, now: datetime | None = None) -> list[int]:
    """Control-plane upkeep: return idle hosts of parked or exited holders."""
    from yoke_core.domain.coordination_claims import active_claim, get_claim
    from yoke_core.domain.qa_host_manual_release import release_host_claim
    from yoke_core.domain.qa_host_turns import lock_host_turn

    if not _table_exists(conn, "qa_test_machine_waits"):
        return []
    current, limit = now or utc_now(), idle_hold_limit()
    due = [
        row
        for row in held_rows(conn)
        if holder_away(row, now=current, limit=limit)
        and current - idle_since(row) >= limit
    ]
    conn.commit()
    released = []
    for row in due:
        claim = get_claim(conn, int(row["id"]))
        machine = str(claim.target.test_machine)
        waiting = _set_reservations(conn, _waiting_executions(conn, machine))
        # Every host this pass releases, locked in name order like record_host_wait.
        for name in sorted({machine, *(str(r["test_machine"]) for r in waiting)}):
            lock_host_turn(conn, _target(name))
        fresh = [r for r in held_rows(conn) if int(r["id"]) == claim.id]
        held = active_claim(conn, claim.target)
        if not fresh or held is None or held.id != claim.id:
            conn.rollback()
            continue
        away = holder_away(fresh[0], now=current, limit=limit)
        if not away or current - idle_since(fresh[0]) < limit:
            conn.rollback()
            continue
        try:
            reason = _release_reason(conn, claim, fresh[0], away, limit)
            return_waiting_set_reservations(conn, machine)
            release_host_claim(conn, claim.id, reason, commit=False)
            conn.commit()
        except Exception:  # noqa: BLE001 - one holder never blocks the rest
            conn.rollback()
            _LOG.warning(
                "qa_host_idle_hold_release_failed: lease %s on %s stays held; "
                "the next upkeep pass retries, or a steering seat releases it "
                "with `yoke coordination-claim release --key QA_HOST:%s "
                "--claim-id %s --holder-session-id %s --reason <why>`",
                claim.id, machine, machine, claim.id, claim.session_id, exc_info=True,
            )
            continue
        released.append(claim.id)
    return released


def _target(test_machine: str) -> Any:
    from yoke_core.domain.work_claim_targets import make_qa_admission_target

    return make_qa_admission_target(test_machine)


__all__ = [
    "child_activity_sql",
    "IDLE_HOLD_RELEASED_REASON",
    "IDLE_HOLD_RESERVATION_REASON",
    "IDLE_HOLD_SETTING",
    "held_qa_hosts",
    "held_qa_hosts_csv",
    "held_qa_hosts_sql",
    "held_rows",
    "holder_away",
    "idle_hold_limit",
    "idle_since",
    "release_idle_host_holds",
    "return_waiting_set_reservations",
]
