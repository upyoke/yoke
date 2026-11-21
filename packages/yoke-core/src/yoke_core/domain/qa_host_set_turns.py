"""A plan execution waits for its hosts from one queue place.

Every host the current case needs gets a live wait at the execution's single
place: the earliest ``queued_at`` of any wait it ever recorded, or the place of
an aborted shared walk it recovers (``qa_host_turn_inheritance``), so the one
queue (``qa_host_queue``) orders each execution once, whichever machine serves
it. A walk any one of several eligible machines serves waits on each of them
as one need. A set can reserve hosts only while it is first on every host it needs.
A partial reservation is returned to the queue if the set loses that place. A
holder reserved its whole set was woken and takes or releases it. The
execution is woken when its last host is reserved and takes the set at once.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, Mapping

from yoke_contracts.timestamps import parse_instant, utc_now
from yoke_core.domain.db_helpers import query_one, query_rows
from yoke_core.domain.qa_plan_execution_store import marker as _p

#: Release intent of a reservation handed to an older waiter on its host.
HOST_TURN_PASSED_REASON = "qa-host-turn-passed-to-older-waiter"
_LIVE = "('waiting','reserved')"


def line_key(wait: Mapping[str, Any]) -> tuple[datetime, str, str]:
    """The order of a wait in the queue; the SQL order of ``machine_waiters``."""
    return (
        parse_instant(wait["queued_at"]),
        str(wait["qa_plan_execution_id"] or wait["session_id"]),
        str(wait["id"]),
    )


def execution_place(
    conn: Any, execution: Mapping[str, Any], machines: Iterable[str]
) -> datetime | None:
    """The one queue place *execution* holds on every host of its set."""
    from yoke_core.domain.qa_host_turn_inheritance import inherited_host_place

    row = query_one(
        conn,
        "SELECT MIN(queued_at) AS place FROM qa_test_machine_waits "
        f"WHERE qa_plan_execution_id={_p(conn)}",
        (str(execution["id"]),),
    )
    if row is not None and row["place"]:
        return parse_instant(row["place"])
    places = []
    for name in machines:
        inherited = inherited_host_place(conn, execution, name)
        if inherited is not None:
            places.append(inherited)
    return min(places) if places else None


def reserved_wait(conn: Any, claim: Any) -> dict[str, Any] | None:
    """The unconsumed wait *claim* reserves, if it is a reservation."""
    from yoke_core.domain.qa_test_machine_wait_schema import (
        QA_TEST_MACHINE_WAIT_TABLE,
    )
    from yoke_core.domain.schema_common import _table_exists

    if not _table_exists(conn, QA_TEST_MACHINE_WAIT_TABLE):
        # Partial fixture schemas without the queue hold no reservation.
        return None
    row = query_one(
        conn,
        "SELECT * FROM qa_test_machine_waits "
        f"WHERE claim_id={_p(conn)} AND state='reserved'",
        (claim.id,),
    )
    return dict(row) if row is not None else None


def execution_waits(conn: Any, execution_id: str) -> list[dict[str, Any]]:
    """Current host waits, including reservations and alternative rows."""
    return [
        dict(row)
        for row in query_rows(
            conn,
            "SELECT * FROM qa_test_machine_waits "
            f"WHERE qa_plan_execution_id={_p(conn)} AND state IN {_LIVE} "
            "ORDER BY test_machine,id",
            (execution_id,),
        )
    ]


def set_at_front(
    conn: Any,
    wait: Mapping[str, Any],
    *,
    exclude_host: str | None = None,
) -> bool:
    """No earlier serving waiter on any required host of a simultaneous set."""
    from yoke_core.domain.qa_host_idle_waiters import serving_waiters

    execution_id = wait["qa_plan_execution_id"]
    if not execution_id or wait["need_id"]:
        return True
    waits = execution_waits(conn, str(execution_id))
    if len(waits) < 2:
        return True
    for row in waits:
        host = str(row["test_machine"])
        if host == exclude_host:
            continue
        if any(
            earlier["qa_plan_execution_id"] != execution_id
            and line_key(earlier) < line_key(row)
            for earlier in serving_waiters(conn, host)
        ):
            return False
    return True


def return_reservations(
    conn: Any, waits: Iterable[Mapping[str, Any]], reason: str
) -> None:
    """Return reserved waits together before releasing any of their claims."""
    from yoke_core.domain.coordination_claims import release
    from yoke_core.domain.db_savepoint import savepoint

    claims = []
    p = _p(conn)
    with savepoint(conn, "qa_return_reservations", owns=False):
        for wait in waits:
            if wait["state"] != "reserved":
                continue
            rows = query_rows(
                conn,
                f"UPDATE qa_test_machine_waits SET state='waiting',claim_id=NULL "
                f"WHERE id={p} AND state='reserved' AND claim_id={p} RETURNING id",
                (str(wait["id"]), wait["claim_id"]),
            )
            if rows:
                claims.append(int(wait["claim_id"]))
        for claim_id in claims:
            release(conn, claim_id, reason, commit=False)


def pass_blocked_set_reservations(conn: Any, claim: Any) -> None:
    """Serve other waiters when this partial set loses the front on any host."""
    holder = reserved_wait(conn, claim)
    if (
        holder is None
        or not awaits_other_hosts(conn, holder)
        or set_at_front(conn, holder)
    ):
        return
    from yoke_core.domain.qa_host_idle_waiters import returnable_reservations

    return_reservations(
        conn,
        returnable_reservations(
            conn, execution_waits(conn, holder["qa_plan_execution_id"])
        ),
        HOST_TURN_PASSED_REASON,
    )


def awaits_other_hosts(conn: Any, wait: Mapping[str, Any]) -> bool:
    """True while the wait's execution still waits for another host.

    The other machine rows of the wait's own need are alternatives, not
    other hosts it needs.
    """
    if not wait["qa_plan_execution_id"]:
        return False
    p = _p(conn)
    need = wait.get("need_id")
    return (
        query_one(
            conn,
            "SELECT id FROM qa_test_machine_waits "
            f"WHERE qa_plan_execution_id={p} AND state='waiting' AND id<>{p}"
            + (f" AND COALESCE(need_id,'')<>{p}" if need else ""),
            (
                str(wait["qa_plan_execution_id"]),
                str(wait["id"]),
                *((str(need),) if need else ()),
            ),
        )
        is not None
    )


def require_host_set_turn(
    conn: Any, execution: Mapping[str, Any], names: tuple[str, ...]
) -> None:
    """Refuse unless every host is free, reserved for *execution*, or held
    over for its session.

    The caller holds every host's turn lock. The first host that is not
    raises the wait the caller queues: lease held, or unhealthy.
    """
    from yoke_core.domain.coordination_claims import active_claim, held_error
    from yoke_core.domain.machine_qa_capability import host_claim_target
    from yoke_core.domain.machine_qa_execution_protocol import (
        MachineQaProtocolLeaseHeld,
    )
    from yoke_core.domain.machine_qa_host_selection import TestMachineHostUnhealthy
    from yoke_core.domain.qa_host_health import host_unhealthy
    from yoke_core.domain.qa_host_holdover import holdover_wait
    from yoke_core.domain.qa_host_turns import reserve_host_turn

    for name in names:
        target = host_claim_target(name)
        reserve_host_turn(conn, target)
        claim = active_claim(conn, target)
        if claim is None:
            health = host_unhealthy(conn, name)
            if health is None:
                continue
            unhealthy = TestMachineHostUnhealthy(health)
            unhealthy.test_machines = names
            raise unhealthy
        wait = reserved_wait(conn, claim)
        if wait is not None and wait["qa_plan_execution_id"] == str(execution["id"]):
            continue
        if holdover_wait(conn, claim) is not None and claim.session_id == str(
            execution["session_id"]
        ):
            continue
        raise MachineQaProtocolLeaseHeld(
            lease=claim,
            test_machine=name,
            contention=held_error(conn, claim).contention,
            test_machines=names,
        )


def record_host_wait(
    conn: Any,
    execution: dict[str, Any],
    *,
    test_machine: str,
    rationale: str,
    test_machines: Iterable[str] = (),
    eligible: Iterable[str] = (),
    commit: bool = True,
) -> dict:
    """Keep the cursor open and queue the execution for the hosts its case needs.

    *test_machines* is a set the case needs all of; *eligible* names the
    machines any one of which serves it, queued as one need. Waits on other
    hosts leave the queue; waits and reservations kept keep their place.
    Every new wait takes the execution's one place.
    """
    from yoke_core.domain.machine_qa_capability import host_claim_target
    from yoke_core.domain.qa_host_idle_waiters import recheck_host_sets
    from yoke_core.domain.qa_host_queue import lock_host_queue, new_need_id
    from yoke_core.domain.qa_host_turns import (
        cancel_host_waits,
        host_wait_view,
        join_host_queue,
        reserve_host_turn,
    )
    from yoke_core.domain.qa_plan_execution_lifecycle import finish_plan_execution

    execution_id = str(execution["id"])
    alternatives = sorted({test_machine, *eligible})
    any_of = len(alternatives) > 1
    machines = alternatives if any_of else sorted({test_machine, *test_machines})
    need_id = new_need_id() if any_of else None
    lock_host_queue(conn)
    live = query_rows(
        conn,
        "SELECT DISTINCT test_machine FROM qa_test_machine_waits "
        f"WHERE qa_plan_execution_id={_p(conn)} AND state IN {_LIVE}",
        (execution_id,),
    )
    left = {str(row["test_machine"]) for row in live} - set(machines)
    if left:
        cancel_host_waits(conn, execution_ids=[execution_id], test_machines=left)
    place = execution_place(conn, execution, machines) or utc_now()
    waits = [
        join_host_queue(
            conn,
            host_claim_target(name),
            session_id=str(execution["session_id"]),
            actor_id=int(execution["actor_id"]),
            resume_command=f"yoke qa plan run --resume-execution-id {execution_id}",
            rationale=rationale
            if name == test_machine
            else f"any of {', '.join(machines)} serves this walk: {rationale}"
            if any_of
            else f"held with {test_machine} for one case: {rationale}",
            execution_id=execution_id,
            queued_at=place,
            need_id=need_id,
        )
        for name in machines
    ]
    finish_plan_execution(
        conn,
        execution,
        state="waiting",
        reason=f"waiting for QA host {test_machine}",
        commit=False,
    )
    recheck_host_sets(conn, machines)
    for name in machines:
        reserve_host_turn(conn, host_claim_target(name))
    if commit:
        conn.commit()
    views = [host_wait_view(conn, wait["id"]) for wait in waits]
    return {
        "state": "waiting",
        "execution_id": execution_id,
        "cursor_ordinal": int(execution["cursor_ordinal"]),
        "host_wait": next(v for v in views if v["test_machine"] == test_machine),
        "host_waits": views,
    }


__all__ = [
    "HOST_TURN_PASSED_REASON",
    "awaits_other_hosts",
    "execution_place",
    "line_key",
    "record_host_wait",
    "require_host_set_turn",
    "reserved_wait",
]
