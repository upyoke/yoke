"""FIFO turns on one physical Test Machine, kept in ``qa_test_machine_waits``.

A session refused a ``QA_HOST:<machine>`` claim, or a scoped QA plan whose
host is leased or unhealthy, joins the line; the host's next release reserves
it for the oldest live waiter and wakes that session, and the waiter's next
acquire consumes the reservation. Scoped QA plan executions and manual
acquires share one line, ordered by when each session first queued; a
walk recovering an aborted shared walk takes that walk's place
(``qa_host_turn_inheritance``). A plan execution waits on every host of its
case at one place, and an unconsumed reservation passes to an older waiter
that joins later (``qa_host_set_turns``). A session that just used a host
keeps it for a short same-session hold-over (``qa_host_holdover``).
"""

from __future__ import annotations

from typing import Any, Iterable
import json
from uuid import uuid4

from yoke_contracts.coordination_claim_recovery import holder_release_command
from yoke_contracts.timestamps import format_instant, utc_now
from yoke_core.domain.machine_idle_notice import note_released_host
from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import instant_parameter, query_one, query_rows
from yoke_core.domain.qa_plan_execution_store import marker as _p
from yoke_core.domain.qa_test_machine_wait_schema import (
    QA_TEST_MACHINE_WAIT_TABLE,
)
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.work_claim_targets import make_qa_admission_target

HOST_TURN_REASON = "qa-host-turn:"
HOST_WAIT_CANCELLED_REASON = "qa-host-wait-cancelled"
_LIVE = "('waiting','reserved')"


def _plan_resume_command(conn: Any, execution: Any) -> str:
    return f"yoke qa plan run --resume-execution-id {execution['id']}"


def _resume_command(conn: Any, wait: Any) -> str:
    if not wait["qa_plan_execution_id"]:
        return str(wait["resume_command"])
    execution = query_one(
        conn,
        f"SELECT * FROM qa_plan_executions WHERE id={_p(conn)}",
        (str(wait["qa_plan_execution_id"]),),
    )
    if execution is None:
        raise ValueError(
            "qa_host_wait_execution_missing: queued execution no longer exists; "
            "ask the control-plane operator to repair this host wait"
        )
    subject = {**execution, "roster": json.loads(execution["roster_json"])}
    return _plan_resume_command(conn, subject)


def _has_line(conn: Any) -> bool:
    """Partial fixture schemas without the line have no waiter to serve."""
    return _table_exists(conn, QA_TEST_MACHINE_WAIT_TABLE)


def lock_host_turn(conn: Any, target: Any) -> None:
    """Serialize queue admission and lease release on the physical host."""
    if target.test_machine and db_backend.connection_is_postgres(conn):
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            ("qa-host-turn:" + target.test_machine,),
        )


def host_line(conn: Any, test_machine: str) -> list[dict[str, Any]]:
    """Waiters still in line for *machine*, oldest first; ended sessions drop out."""
    if not _has_line(conn):
        return []
    rows = query_rows(
        conn,
        "SELECT w.* FROM qa_test_machine_waits w JOIN harness_sessions s "
        "ON s.session_id=w.session_id "
        f"WHERE w.test_machine={_p(conn)} AND w.state='waiting' AND s.ended_at IS NULL "
        "ORDER BY w.queued_at, COALESCE(w.qa_plan_execution_id, w.session_id), w.id",
        (test_machine,),
    )
    return [dict(row) for row in rows]


def host_wait_view(conn: Any, wait_id: str) -> dict[str, Any]:
    """Return one wait with its current place in its machine's line."""
    row = query_one(
        conn, f"SELECT * FROM qa_test_machine_waits WHERE id={_p(conn)}", (wait_id,)
    )
    assert row is not None
    line = [str(waiter["id"]) for waiter in host_line(conn, str(row["test_machine"]))]
    return {
        "id": str(row["id"]),
        "test_machine": str(row["test_machine"]),
        "state": str(row["state"]),
        "queued_at": format_instant(row["queued_at"]),
        "resume_command": _resume_command(conn, row),
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
    queued_at: Any = None,
) -> dict[str, Any]:
    """Queue *session_id* at *queued_at* or now; a queued session keeps its place.

    A live wait moves only earlier, to a *queued_at* before its own.
    """
    p = _p(conn)
    test_machine = str(target.test_machine)
    lock_host_turn(conn, target)
    live = query_one(
        conn,
        f"SELECT id FROM qa_test_machine_waits WHERE test_machine={p} AND session_id={p} "
        f"AND state IN {_LIVE}",
        (test_machine, session_id),
    )
    if live is None:
        wait_id = str(uuid4())
        conn.execute(
            "INSERT INTO qa_test_machine_waits(id,test_machine,session_id,actor_id,queued_at,"
            "qa_plan_execution_id,state,resume_command,rationale) "
            f"VALUES({p},{p},{p},{p},{p},{p},'waiting',{p},{p})",
            (
                wait_id,
                test_machine,
                session_id,
                int(actor_id),
                instant_parameter(conn, queued_at or utc_now()),
                execution_id,
                resume_command,
                rationale,
            ),
        )
    else:
        wait_id = str(live["id"])
        conn.execute(
            f"UPDATE qa_test_machine_waits SET resume_command={p},rationale={p},"
            f"qa_plan_execution_id=COALESCE({p},qa_plan_execution_id) WHERE id={p}",
            (resume_command, rationale, execution_id, wait_id),
        )
        if queued_at is not None:
            place = instant_parameter(conn, queued_at)
            conn.execute(
                f"UPDATE qa_test_machine_waits SET queued_at={p} "
                f"WHERE id={p} AND queued_at>{p}",
                (place, wait_id, place),
            )
    return host_wait_view(conn, wait_id)


def reserve_host_turn(conn: Any, target: Any) -> None:
    """Reserve a free, healthy host for the oldest live waiter.

    A host reserved for a younger waiter passes to the older one first.
    An unhealthy host keeps its line waiting and stays free for the operator
    verify or golden capture that heals it; that operation's release serves
    the line.
    """
    if not target.test_machine:
        return
    from yoke_core.domain.coordination_claims import active_claim, acquire
    from yoke_core.domain.qa_host_health import host_unhealthy
    from yoke_core.domain.qa_host_holdover import expire_holdover
    from yoke_core.domain.qa_host_set_turns import pass_to_older_waiter

    held = active_claim(conn, target)
    if held is not None:
        # Releasing a lapsed hold-over or a passed reservation serves the
        # line through this function.
        if not expire_holdover(conn, held):
            pass_to_older_waiter(conn, held)
        return
    if host_unhealthy(conn, target.test_machine) is not None:
        return
    line = host_line(conn, target.test_machine)
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
        f"UPDATE qa_test_machine_waits SET state='reserved',claim_id={_p(conn)} "
        f"WHERE id={_p(conn)}",
        (claim.id, str(first["id"])),
    )
    _wake_waiter(conn, first, claim)


def _wake_waiter(conn: Any, wait: dict[str, Any], claim: Any) -> None:
    from yoke_contracts.session_control.models import RecipientSelector
    from yoke_core.domain.session_explicit_wake import mark_explicit_stopped_wake
    from yoke_core.domain.session_message_service import send_message
    from yoke_core.domain.qa_host_set_turns import awaits_other_hosts

    if awaits_other_hosts(conn, wait):
        # The reservation that completes the execution's host set wakes it.
        return
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
            f"QA host turn ready: {wait['test_machine']}; reserved lease {claim.id} "
            f"for this session. Take it with: {_resume_command(conn, wait)}."
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
        f"UPDATE qa_test_machine_waits SET state='granted',settled_at={p} "
        f"WHERE claim_id={p} AND session_id={p} AND state='reserved'",
        (instant_parameter(conn, utc_now()), claim.id, session_id),
    )
    return cursor.rowcount == 1


def host_claim_released(conn: Any, claim: Any) -> None:
    """Drop the unconsumed reservation, ending a wait it orphans; serve the line.

    A direct operation's release may first keep the host for its session as a
    hold-over (``qa_host_holdover``).
    """
    from yoke_core.domain.qa_host_holdover import hold_over_direct_operation
    from yoke_core.domain.qa_host_turn_release import cancel_released_reservation

    if not claim.target.test_machine:
        return
    if _has_line(conn):
        cancel_released_reservation(conn, claim)
        if not hold_over_direct_operation(conn, claim):
            reserve_host_turn(conn, claim.target)
    note_released_host(conn, claim.target)


def cancel_host_waits(
    conn: Any,
    *,
    session_id: str | None = None,
    execution_ids: Iterable[str] = (),
    test_machines: Iterable[str] = (),
) -> None:
    """Leave every line the session or executions wait in, or only the
    lines of *test_machines* when named.

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
    machines = sorted(str(value) for value in test_machines)
    if machines:
        where += f" AND test_machine IN ({','.join([p] * len(machines))})"
        params = (*params, *machines)
    if not _has_line(conn):
        return
    rows = query_rows(
        conn,
        f"SELECT id,test_machine,claim_id,state FROM qa_test_machine_waits "
        f"WHERE state IN {_LIVE} AND {where} ORDER BY test_machine,id",
        params,
    )
    if not rows:
        return
    for test_machine in sorted({str(row["test_machine"]) for row in rows}):
        lock_host_turn(conn, make_qa_admission_target(test_machine))
    now = instant_parameter(conn, utc_now())
    for row in rows:
        conn.execute(
            f"UPDATE qa_test_machine_waits SET state='cancelled',settled_at={p} WHERE id={p}",
            (now, str(row["id"])),
        )
    for row in rows:
        if row["state"] == "reserved" and row["claim_id"] is not None:
            release(
                conn, int(row["claim_id"]), HOST_WAIT_CANCELLED_REASON, commit=False
            )
