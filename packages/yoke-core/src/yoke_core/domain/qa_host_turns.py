"""Serve exclusive Test Machine turns from the shared host queue.

A waiter's next acquire consumes its reservation. Plans wait at one place
across all their required hosts, and a recently used host can stay reserved
briefly as a same-session hold-over.
"""

from __future__ import annotations

from typing import Any, Iterable
import json
from uuid import uuid4

from yoke_contracts.coordination_claim_recovery import holder_release_command
from yoke_contracts.timestamps import format_instant, utc_now
from yoke_core.domain.machine_idle_notice import note_released_host
from yoke_core.domain.db_helpers import instant_parameter, query_one, query_rows
from yoke_core.domain.qa_host_queue import (
    lock_host_queue,
    machine_waiters as queue_machine_waiters,
    queue_entry,
    position_text,
    settle_need,
    waits_for_text,
)
from yoke_core.domain.qa_plan_execution_store import marker as _p
from yoke_core.domain.qa_test_machine_wait_schema import (
    QA_TEST_MACHINE_WAIT_TABLE,
)
from yoke_core.domain.schema_common import _table_exists

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
    """Partial fixture schemas without the queue have no waiter to serve."""
    return _table_exists(conn, QA_TEST_MACHINE_WAIT_TABLE)


def lock_host_turn(conn: Any, target: Any) -> None:
    """Serialize a host target's turn decisions under the one queue lock."""
    if target.test_machine:
        lock_host_queue(conn)


def machine_waiters(conn: Any, test_machine: str) -> list[dict[str, Any]]:
    """The queue's live waits *test_machine* can serve, oldest first."""
    if not _has_line(conn):
        return []
    return queue_machine_waiters(conn, test_machine)


def host_wait_view(conn: Any, wait_id: str) -> dict[str, Any]:
    """Return one wait with its waiter's current place in the queue."""
    row = query_one(
        conn, f"SELECT * FROM qa_test_machine_waits WHERE id={_p(conn)}", (wait_id,)
    )
    assert row is not None
    entry = queue_entry(conn, wait_id)
    places = entry["places"] if entry else {}
    position, length = places.get(str(row["test_machine"]), (None, 0))
    return {
        "id": str(row["id"]),
        "test_machine": str(row["test_machine"]),
        "test_machines": entry["test_machines"]
        if entry
        else [str(row["test_machine"])],
        "waits_for": waits_for_text(entry) if entry else str(row["test_machine"]),
        "state": str(row["state"]),
        "queued_at": format_instant(row["queued_at"]),
        "resume_command": _resume_command(conn, row),
        "rationale": str(row["rationale"] or ""),
        "position": position,
        "places": places,
        "position_text": position_text(places),
        "queue_length": length,
    }


def join_host_queue(
    conn: Any,
    target: Any,
    *,
    session_id: str,
    actor_id: int,
    resume_command: str,
    rationale: str = "",
    execution_id: str | None = None,
    queued_at: Any = None,
    need_id: str | None = None,
) -> dict[str, Any]:
    """Queue a host wait for an execution or, for a manual acquire, its session.

    A queued owner keeps its place unless given an earlier *queued_at*.
    Rows sharing *need_id* are one waiter's alternative machines.
    """
    p = _p(conn)
    test_machine = str(target.test_machine)
    lock_host_turn(conn, target)
    live = query_one(
        conn,
        f"SELECT id FROM qa_test_machine_waits WHERE test_machine={p} AND state IN {_LIVE} "
        f"AND (qa_plan_execution_id={p} OR (qa_plan_execution_id IS NULL AND session_id={p})) "
        "ORDER BY qa_plan_execution_id IS NULL LIMIT 1",
        (test_machine, execution_id, session_id),
    )
    if live is None:
        wait_id = str(uuid4())
        conn.execute(
            "INSERT INTO qa_test_machine_waits(id,test_machine,session_id,actor_id,queued_at,"
            "qa_plan_execution_id,state,resume_command,rationale,need_id) "
            f"VALUES({p},{p},{p},{p},{p},{p},'waiting',{p},{p},{p})",
            (
                wait_id,
                test_machine,
                session_id,
                int(actor_id),
                instant_parameter(conn, queued_at or utc_now()),
                execution_id,
                resume_command,
                rationale,
                need_id,
            ),
        )
    else:
        wait_id = str(live["id"])
        conn.execute(
            f"UPDATE qa_test_machine_waits SET resume_command={p},rationale={p},"
            f"qa_plan_execution_id=COALESCE({p},qa_plan_execution_id),need_id={p} "
            f"WHERE id={p}",
            (resume_command, rationale, execution_id, need_id, wait_id),
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
    """Reserve a free, healthy host for the oldest live waiter it can serve.

    A set-waiter away past the idle hold keeps its place but is passed over
    (``qa_host_idle_waiters``).

    An unhealthy host keeps its waiters waiting and stays free for the operator
    reset, verify or golden capture that heals it; that operation's release serves
    the queue.
    """
    if not target.test_machine:
        return
    from yoke_core.domain.coordination_claims import active_claim, acquire
    from yoke_core.domain.qa_host_health import host_unhealthy
    from yoke_core.domain.qa_host_holdover import expire_holdover
    from yoke_core.domain.qa_host_set_turns import pass_blocked_set_reservations

    held = active_claim(conn, target)
    if held is not None:
        # Releasing a lapsed hold-over or a passed reservation serves the
        # queue through this function.
        if not expire_holdover(conn, held):
            pass_blocked_set_reservations(conn, held)
        return
    if host_unhealthy(conn, target.test_machine) is not None:
        return
    from yoke_core.domain.qa_host_slot_turns import front_waiter

    # A slotted set's front waiter takes a host for every slot at once.
    first = front_waiter(conn, target)
    if first is None:
        return
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
    resume = _resume_command(conn, wait)
    take, open_requirement = f"Take it with: {resume}.", ""
    if wait["qa_plan_execution_id"]:
        plan_args = resume.removeprefix("yoke qa plan run ")
        take = (
            "Take it on this same connection through the plan watcher: run "
            f"`yoke watch qa-plan --print-streaming-pair -- {plan_args}`, then run "
            "the invocation it prints once."
        )
        open_requirement = (
            " The requirement is still open; restore its declared starting state "
            "before walking."
        )
    created = send_message(
        conn,
        actor_id=int(wait["actor_id"]),
        sender_session_id=None,
        selector=RecipientSelector(session_ids=[str(wait["session_id"])]),
        body=(
            f"QA host turn ready: {wait['test_machine']}; reserved lease {claim.id} "
            f"for this session. {take}{open_requirement} If you no longer need "
            "this turn, release it before taking it so the next waiter gets it: "
            f"`{holder_release_command(claim.id)}`."
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
    from yoke_core.domain.qa_host_turn_borrow import turn_in_operation

    if (
        claim.session_id != session_id
        or not _has_line(conn)
        or turn_in_operation(claim)
    ):
        return False
    p = _p(conn)
    rows = query_rows(
        conn,
        f"UPDATE qa_test_machine_waits SET state='granted',settled_at={p} "
        f"WHERE claim_id={p} AND session_id={p} AND state='reserved' "
        "RETURNING id,need_id",
        (instant_parameter(conn, utc_now()), claim.id, session_id),
    )
    for row in rows:
        settle_need(conn, row)
    return len(rows) == 1


def host_claim_released(conn: Any, claim: Any) -> None:
    """Drop the unconsumed reservation, ending a wait it orphans; serve the queue.

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
    manual_only: bool = False,
) -> None:
    """Cancel waits for a session or executions, filtered by host or manual ownership.

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
    if manual_only:
        where += " AND qa_plan_execution_id IS NULL"
    if not _has_line(conn):
        return
    lock_host_queue(conn)
    rows = query_rows(
        conn,
        f"SELECT id,test_machine,claim_id,state FROM qa_test_machine_waits "
        f"WHERE state IN {_LIVE} AND {where} ORDER BY test_machine,id",
        params,
    )
    if not rows:
        return
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
