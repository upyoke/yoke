"""A session about to use a Test Machine again keeps its turn for a short hold-over.

Two releases used to hand a host away from the session that needed it next:

* A direct operation (``yoke test-machine exec``, desktop access, browser
  sign-in) takes and drops a lease per command and holds no place in the queue, so
  on a free host another session could take it between a preflight's release
  and the preflighting session's ``yoke qa case run``.
* A session aborting its own stale execution (``served_build_changed`` after a
  deploy) released the turn that execution held or had reserved, and the queue's
  next waiter took it before the session's rematerialized execution asked.

Each now leaves a same-session hold-over: the host's claim stays held for the
session with :data:`HOLDOVER_REASON`, beside a ``reserved`` wait with no
execution, and the session's next acquire of the host consumes it like any
reserved turn (``qa_host_turns.reservation_for``). A direct operation leaves one
only on an empty queue, so a session already queued keeps its turn, or when it
consumed the session's hold-over, which every waiter queued behind; an aborted
execution leaves one whatever the queue holds, because its turn was already
earned ahead of every waiter. The hold-over reason carries the host-turn prefix,
so taking it never serves the queue first. A hold-over lasts :data:`HOLDOVER_TTL`
from its wait's ``queued_at``; claim heartbeats never extend it, since every tool
call of the session stamps all its claims. A renewal while another session waits
keeps the first hold-over's start, so a session polling with direct operations
cannot starve the queue. Any acquire on the host, or control-plane upkeep,
releases an expired one, and that release serves the queue.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from yoke_contracts.timestamps import format_instant, parse_instant, utc_now
from yoke_core.domain.db_helpers import instant_parameter, query_one, query_rows
from yoke_core.domain.qa_host_turns import HOST_TURN_REASON
from yoke_core.domain.qa_plan_execution_store import marker as _p

HOLDOVER_REASON = HOST_TURN_REASON + "holdover"
_RATIONALE = "hold-over for this session"
HOLDOVER_EXPIRED_REASON = "qa-host-holdover-expired"
HOLDOVER_TTL = timedelta(seconds=120)
#: The reason a direct operation's own lease carries (``test_machine.lease_acquire``).
DIRECT_OPERATION_REASON = "test-machine direct operation"
#: Set on an execution its own session stops (``qa_plan_execution_stop``).
OWNER_ABORT = "owner_abort"


def holdover_expires_at(wait: Any) -> datetime:
    """When the hold-over *wait* lapses."""
    return parse_instant(wait["queued_at"]) + HOLDOVER_TTL


def holdover_wait(conn: Any, claim: Any) -> dict[str, Any] | None:
    """The unconsumed hold-over wait *claim* reserves, if it is one."""
    from yoke_core.domain.qa_host_set_turns import reserved_wait

    if claim.reason != HOLDOVER_REASON:
        return None
    wait = reserved_wait(conn, claim)
    return wait if wait is not None and not wait["qa_plan_execution_id"] else None


def holdover_view(conn: Any, test_machine: str, session_id: str) -> dict[str, Any] | None:
    """The session's live hold-over of *test_machine*, as operators read it."""
    from yoke_core.domain.coordination_claims import active_claim
    from yoke_core.domain.machine_qa_capability import host_claim_target

    claim = active_claim(conn, host_claim_target(test_machine))
    wait = holdover_wait(conn, claim) if claim is not None else None
    if wait is None or claim.session_id != session_id:
        return None
    return {
        "claim_id": claim.id,
        "test_machine": test_machine,
        "expires_at": format_instant(holdover_expires_at(wait)),
    }


def session_holdovers(conn: Any, session_id: str) -> list[dict[str, Any]]:
    """Every live hold-over *session_id* keeps, for its receipts."""
    rows = query_rows(
        conn,
        "SELECT DISTINCT test_machine FROM qa_test_machine_waits "
        f"WHERE session_id={_p(conn)} AND state='reserved' AND qa_plan_execution_id IS NULL "
        "ORDER BY test_machine",
        (session_id,),
    )
    views = (holdover_view(conn, str(row["test_machine"]), session_id) for row in rows)
    return [view for view in views if view is not None]


def _session_live(conn: Any, session_id: str) -> bool:
    row = query_one(
        conn, f"SELECT ended_at FROM harness_sessions WHERE session_id={_p(conn)}", (session_id,)
    )
    return row is not None and row["ended_at"] is None


def _hold(
    conn: Any, claim_id: int, *, test_machine: str, session_id: str, actor_id: Any,
    start: datetime | None = None,
) -> None:
    """Keep live claim *claim_id* for *session_id* as a hold-over from *start*."""
    from yoke_core.domain.claim_chain_state import record_claim_reason

    p, start = _p(conn), start or utc_now()
    expires = format_instant(start + HOLDOVER_TTL)
    record_claim_reason(conn, claim_id=claim_id, reason=HOLDOVER_REASON)
    conn.execute(
        "INSERT INTO qa_test_machine_waits(id,test_machine,session_id,actor_id,queued_at,"
        "state,claim_id,resume_command,rationale) "
        f"VALUES({p},{p},{p},{p},{p},'reserved',{p},{p},{p})",
        (
            str(uuid4()),
            test_machine,
            session_id,
            int(actor_id),
            instant_parameter(conn, start),
            claim_id,
            "this session's next acquire of the host: yoke qa case run, "
            "yoke qa plan run, or yoke test-machine exec",
            f"{_RATIONALE} until {expires}; then the queue is served",
        ),
    )


def _consumed_holdover_start(conn: Any, claim: Any) -> datetime | None:
    """When the hold-over *claim* was taken by consuming began, if it was one."""
    row = query_one(
        conn,
        "SELECT queued_at FROM qa_test_machine_waits WHERE claim_id="
        f"{_p(conn)} AND state='granted' AND qa_plan_execution_id IS NULL "
        f"AND rationale LIKE {_p(conn)} ORDER BY queued_at LIMIT 1",
        (claim.id, _RATIONALE + "%"),
    )
    return parse_instant(row["queued_at"]) if row is not None else None


def hold_over_direct_operation(conn: Any, claim: Any) -> bool:
    """Hold a direct operation's released host for its session, before the
    queue is served; False leaves the release to serve it."""
    from yoke_core.domain.coordination_claims import acquire, active_claim
    from yoke_core.domain.qa_host_turns import machine_waiters

    test_machine = str(claim.target.test_machine)
    if (
        claim.reason != DIRECT_OPERATION_REASON
        or claim.actor_id is None
        or active_claim(conn, claim.target) is not None
        or not _session_live(conn, claim.session_id)
    ):
        return False
    start = None
    if machine_waiters(conn, test_machine):
        # Waiters queued behind the hold-over this lease consumed; it keeps
        # that hold-over's start, and a lapsed one serves the queue.
        start = _consumed_holdover_start(conn, claim)
        if start is None or utc_now() >= start + HOLDOVER_TTL:
            return False
    held = acquire(conn, claim.target, claim.session_id, reason=HOLDOVER_REASON, commit=False)
    _hold(
        conn, held.id, test_machine=test_machine,
        session_id=claim.session_id, actor_id=claim.actor_id, start=start,
    )
    return True


def _owner_aborted(execution: dict[str, Any]) -> bool:
    """The execution's own session asked for this abort, now or before a walk-end."""
    from yoke_core.domain.qa_plan_execution_abort_state import abort_request

    request = abort_request(execution)
    if request is not None:
        return request.get("requested_by_session_id") == str(execution["session_id"])
    return bool(execution.get(OWNER_ABORT))


def carry_aborted_execution_hosts(conn: Any, execution: dict[str, Any], *, state: str) -> None:
    """Hold every host an execution its live session aborts held or had reserved.

    Only the owner's own stop carries: a steering stop, a manual lease release,
    a turn release or a stale-execution sweep ends custody and serves the queue.
    Run before the execution's waits are cancelled and its leases released: a
    carried reservation leaves the execution, a carried lease drops its
    execution reason, and a carried primary lease leaves ``execution``.
    """
    from yoke_core.domain.coordination_claims import get_claim
    from yoke_core.domain.qa_host_turns import lock_host_turn
    from yoke_core.domain.qa_plan_host_leases import execution_host_leases

    session_id = str(execution["session_id"])
    if state != "aborted" or not _owner_aborted(execution) or not _session_live(conn, session_id):
        return
    p = _p(conn)
    reserved = query_rows(
        conn,
        "SELECT id,claim_id FROM qa_test_machine_waits "
        f"WHERE qa_plan_execution_id={p} AND state='reserved' AND claim_id IS NOT NULL",
        (str(execution["id"]),),
    )
    claims = [get_claim(conn, int(row["claim_id"])) for row in reserved]
    if reserved:
        conn.execute(
            "UPDATE qa_test_machine_waits SET state='cancelled',settled_at="
            f"{p} WHERE id IN ({','.join([p] * len(reserved))})",
            (instant_parameter(conn, utc_now()), *(str(row["id"]) for row in reserved)),
        )
    primary = execution.get("test_machine_lease_id")
    leases = execution_host_leases(conn, execution)
    if primary is not None and primary not in {claim.id for claim in leases}:
        leases.append(get_claim(conn, int(primary)))
    for claim in sorted([*claims, *leases], key=lambda c: str(c.target.test_machine)):
        if not claim.is_active or claim.session_id != session_id:
            continue
        lock_host_turn(conn, claim.target)
        _hold(
            conn, claim.id, test_machine=str(claim.target.test_machine),
            session_id=session_id, actor_id=execution["actor_id"],
        )
        if claim.id == primary:
            execution["test_machine_lease_id"] = None


def expire_holdover(conn: Any, claim: Any, *, now: datetime | None = None) -> bool:
    """Release *claim* when it is a lapsed hold-over; the release serves the queue."""
    from yoke_core.domain.coordination_claims import release

    wait = holdover_wait(conn, claim)
    if wait is None or (now or utc_now()) < holdover_expires_at(wait):
        return False
    release(conn, claim.id, HOLDOVER_EXPIRED_REASON, commit=False)
    return True


def expire_holdovers(conn: Any) -> list[int]:
    """Control-plane upkeep: release every lapsed hold-over and commit."""
    from yoke_core.domain.coordination_claims import active_claim, get_claim
    from yoke_core.domain.qa_host_turns import lock_host_turn
    from yoke_core.domain.schema_common import _table_exists

    if not _table_exists(conn, "qa_test_machine_waits"):
        return []
    rows = query_rows(
        conn,
        f"SELECT id FROM work_claims WHERE reason={_p(conn)} AND released_at IS NULL "
        "ORDER BY id",
        (HOLDOVER_REASON,),
    )
    expired = []
    for row in rows:
        target = get_claim(conn, int(row["id"])).target
        lock_host_turn(conn, target)
        claim = active_claim(conn, target)
        if claim is not None and claim.id == int(row["id"]) and expire_holdover(conn, claim):
            expired.append(claim.id)
        conn.commit()
    return expired


__all__ = [
    "DIRECT_OPERATION_REASON",
    "HOLDOVER_EXPIRED_REASON",
    "HOLDOVER_REASON",
    "HOLDOVER_TTL",
    "OWNER_ABORT",
    "carry_aborted_execution_hosts",
    "expire_holdover",
    "expire_holdovers",
    "hold_over_direct_operation",
    "holdover_expires_at",
    "holdover_view",
    "holdover_wait",
    "session_holdovers",
]
