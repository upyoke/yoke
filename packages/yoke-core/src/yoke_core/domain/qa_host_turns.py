"""FIFO turns on one physical Test Machine, kept in the ``qa_host_waits`` line.

A session refused a ``QA_HOST:<machine>`` claim, or a scoped QA plan whose
host is leased or unhealthy, joins the line; the host's next release reserves
it for the oldest live waiter and wakes that session, and the waiter's next
acquire consumes the reservation. Scoped QA plan executions and manual
acquires share one line, ordered by when each session first queued.
"""

from __future__ import annotations

from typing import Any, Iterable
from uuid import uuid4

from yoke_contracts.coordination_claim_recovery import holder_release_command
from yoke_contracts.timestamps import format_instant, utc_now
from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import instant_parameter, query_one, query_rows
from yoke_core.domain.qa_host_wait_schema import QA_HOST_WAIT_TABLE
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.work_claim_targets import make_qa_admission_target

HOST_TURN_REASON = "qa-host-turn:"
HOST_WAIT_CANCELLED_REASON = "qa-host-wait-cancelled"
_LIVE = "('waiting','reserved')"


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _has_line(conn: Any) -> bool:
    """Partial fixture schemas without the line have no waiter to serve."""
    return _table_exists(conn, QA_HOST_WAIT_TABLE)


def lock_host_turn(conn: Any, target: Any) -> None:
    """Serialize queue admission and lease release on the physical host."""
    if target.machine_id and db_backend.connection_is_postgres(conn):
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            ("qa-host-turn:" + target.machine_id,),
        )


def host_line(conn: Any, machine: str) -> list[dict[str, Any]]:
    """Waiters still in line for *machine*, oldest first; ended sessions drop out."""
    if not _has_line(conn):
        return []
    rows = query_rows(
        conn,
        "SELECT w.* FROM qa_host_waits w JOIN harness_sessions s "
        "ON s.session_id=w.session_id "
        f"WHERE w.machine_id={_p(conn)} AND w.state='waiting' AND s.ended_at IS NULL "
        "ORDER BY w.queued_at, w.id",
        (machine,),
    )
    return [dict(row) for row in rows]


def host_wait_view(conn: Any, wait_id: str) -> dict[str, Any]:
    """Return one wait with its current place in its machine's line."""
    row = query_one(
        conn, f"SELECT * FROM qa_host_waits WHERE id={_p(conn)}", (wait_id,)
    )
    assert row is not None
    line = [str(waiter["id"]) for waiter in host_line(conn, str(row["machine_id"]))]
    return {
        "id": str(row["id"]),
        "machine": str(row["machine_id"]),
        "state": str(row["state"]),
        "queued_at": format_instant(row["queued_at"]),
        "resume_command": str(row["resume_command"]),
        "rationale": str(row["rationale"] or ""),
        "position": line.index(wait_id) + 1 if wait_id in line else None,
        "line_length": len(line),
    }


def join_host_line(
    conn: Any,
    target: Any,
    *,
    session_id: str,
    actor_id: int,
    resume_command: str,
    rationale: str = "",
    execution_id: str | None = None,
) -> dict[str, Any]:
    """Queue *session_id* for the host; a session already in line keeps its place."""
    p = _p(conn)
    machine = str(target.machine_id)
    lock_host_turn(conn, target)
    live = query_one(
        conn,
        f"SELECT id FROM qa_host_waits WHERE machine_id={p} AND session_id={p} "
        f"AND state IN {_LIVE}",
        (machine, session_id),
    )
    if live is None:
        wait_id = str(uuid4())
        conn.execute(
            "INSERT INTO qa_host_waits(id,machine_id,session_id,actor_id,queued_at,"
            "qa_plan_execution_id,state,resume_command,rationale) "
            f"VALUES({p},{p},{p},{p},{p},{p},'waiting',{p},{p})",
            (
                wait_id,
                machine,
                session_id,
                int(actor_id),
                instant_parameter(conn, utc_now()),
                execution_id,
                resume_command,
                rationale,
            ),
        )
    else:
        wait_id = str(live["id"])
        conn.execute(
            f"UPDATE qa_host_waits SET resume_command={p},rationale={p},"
            f"qa_plan_execution_id=COALESCE({p},qa_plan_execution_id) WHERE id={p}",
            (resume_command, rationale, execution_id, wait_id),
        )
    return host_wait_view(conn, wait_id)


def reserve_host_turn(conn: Any, target: Any) -> None:
    """Reserve a free, healthy host for the oldest live waiter.

    An unhealthy host keeps its line waiting and stays free for the operator
    verify or golden capture that heals it; that operation's release serves
    the line.
    """
    if not target.machine_id:
        return
    from yoke_core.domain.coordination_claims import active_claim, acquire
    from yoke_core.domain.qa_host_health import host_unhealthy

    if active_claim(conn, target) is not None:
        return
    if host_unhealthy(conn, target.machine_id) is not None:
        return
    line = host_line(conn, target.machine_id)
    if not line:
        return
    first = line[0]
    claim = acquire(
        conn,
        target,
        str(first["session_id"]),
        reason=HOST_TURN_REASON + str(first["id"]),
        commit=False,
    )
    conn.execute(
        f"UPDATE qa_host_waits SET state='reserved',claim_id={_p(conn)} "
        f"WHERE id={_p(conn)}",
        (claim.id, str(first["id"])),
    )
    _wake_waiter(conn, first, claim)


def _wake_waiter(conn: Any, wait: dict[str, Any], claim: Any) -> None:
    from yoke_contracts.session_control.models import RecipientSelector
    from yoke_core.domain.session_explicit_wake import mark_explicit_stopped_wake
    from yoke_core.domain.session_message_service import send_message

    open_requirement = (
        " The requirement is still open; restore its declared starting state "
        "before walking."
        if wait["qa_plan_execution_id"]
        else ""
    )
    created = send_message(
        conn,
        actor_id=int(wait["actor_id"]),
        sender_session_id=None,
        selector=RecipientSelector(session_ids=[str(wait["session_id"])]),
        body=(
            f"QA host turn ready: {wait['machine_id']}; reserved lease {claim.id} "
            f"for this session. Take it with: {wait['resume_command']}."
            f"{open_requirement} If you no longer need the host, release it "
            f"so the next waiter gets it: `{holder_release_command(claim.id)}`."
        ),
        idempotency_key=f"qa-host-turn:{wait['id']}:{claim.id}",
        idempotency_intent_only=True,
        commit=False,
    )
    mark_explicit_stopped_wake(
        conn,
        message_id=str(created["message_id"]),
        session_id=str(wait["session_id"]),
    )


def reservation_for(conn: Any, claim: Any, session_id: str) -> bool:
    """Consume the caller's own unconsumed reservation of *claim*."""
    if claim.session_id != session_id or not _has_line(conn):
        return False
    p = _p(conn)
    cursor = conn.execute(
        f"UPDATE qa_host_waits SET state='granted',settled_at={p} "
        f"WHERE claim_id={p} AND session_id={p} AND state='reserved'",
        (instant_parameter(conn, utc_now()), claim.id, session_id),
    )
    return cursor.rowcount == 1


def host_claim_released(conn: Any, claim: Any) -> None:
    """A released host drops its unconsumed reservation, then serves the line."""
    if not claim.target.machine_id or not _has_line(conn):
        return
    p = _p(conn)
    conn.execute(
        f"UPDATE qa_host_waits SET state='cancelled',settled_at={p} "
        f"WHERE claim_id={p} AND state='reserved'",
        (instant_parameter(conn, utc_now()), claim.id),
    )
    reserve_host_turn(conn, claim.target)


def cancel_host_waits(
    conn: Any,
    *,
    session_id: str | None = None,
    execution_ids: Iterable[str] = (),
) -> None:
    """Leave every line the session or executions wait in.

    Every matching wait is cancelled before any reservation is released, so
    a released turn never passes to another wait this same call removes.
    """
    from yoke_core.domain.coordination_claims import release

    p = _p(conn)
    executions = [str(value) for value in execution_ids]
    if session_id is not None:
        where, params = f"session_id={p}", (session_id,)
    elif executions:
        where = f"qa_plan_execution_id IN ({','.join([p] * len(executions))})"
        params = tuple(executions)
    else:
        return
    if not _has_line(conn):
        return
    rows = query_rows(
        conn,
        f"SELECT id,machine_id,claim_id,state FROM qa_host_waits "
        f"WHERE state IN {_LIVE} AND {where} ORDER BY machine_id,id",
        params,
    )
    if not rows:
        return
    for machine in sorted({str(row["machine_id"]) for row in rows}):
        lock_host_turn(conn, make_qa_admission_target(machine))
    now = instant_parameter(conn, utc_now())
    for row in rows:
        conn.execute(
            f"UPDATE qa_host_waits SET state='cancelled',settled_at={p} WHERE id={p}",
            (now, str(row["id"])),
        )
    for row in rows:
        if row["state"] == "reserved" and row["claim_id"] is not None:
            release(
                conn, int(row["claim_id"]), HOST_WAIT_CANCELLED_REASON, commit=False
            )


def record_host_wait(
    conn: Any,
    execution: dict[str, Any],
    *,
    machine: str,
    rationale: str,
    commit: bool = True,
) -> dict:
    """Keep the cursor open, queue the execution's session, release its hosts."""
    from yoke_core.domain.machine_qa_capability import host_claim_target
    from yoke_core.domain.qa_plan_execution_continuation import continuation_recipe
    from yoke_core.domain.qa_plan_execution_lifecycle import finish_plan_execution

    p = _p(conn)
    execution_id = str(execution["id"])
    target = host_claim_target(machine)
    moved = query_rows(
        conn,
        f"SELECT machine_id FROM qa_host_waits WHERE qa_plan_execution_id={p} "
        f"AND state IN {_LIVE} AND machine_id<>{p}",
        (execution_id, machine),
    )
    machines = {machine} | {str(row["machine_id"]) for row in moved}
    for name in sorted(machines):
        lock_host_turn(conn, host_claim_target(name))
    if moved:
        # One execution waits on one host: moving hosts leaves the old line.
        cancel_host_waits(conn, execution_ids=[execution_id])
    # Queue before releasing: release atomically grants the next FIFO turn.
    wait = join_host_line(
        conn,
        target,
        session_id=str(execution["session_id"]),
        actor_id=int(execution["actor_id"]),
        resume_command=continuation_recipe(conn, execution).removesuffix(
            " --continue-mission"
        ),
        rationale=rationale,
        execution_id=execution_id,
    )
    finish_plan_execution(
        conn,
        execution,
        state="waiting",
        reason=f"waiting for QA host {machine}",
        commit=False,
    )
    reserve_host_turn(conn, target)
    if commit:
        conn.commit()
    return {
        "state": "waiting",
        "execution_id": execution_id,
        "cursor_ordinal": int(execution["cursor_ordinal"]),
        "host_wait": host_wait_view(conn, wait["id"]),
    }


__all__ = [
    "HOST_TURN_REASON",
    "HOST_WAIT_CANCELLED_REASON",
    "cancel_host_waits",
    "host_claim_released",
    "host_line",
    "host_wait_view",
    "join_host_line",
    "lock_host_turn",
    "record_host_wait",
    "reservation_for",
    "reserve_host_turn",
]
