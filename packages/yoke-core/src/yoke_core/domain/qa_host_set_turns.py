"""A plan execution waits for its whole host set from one queue place.

Every host the current case needs gets a live wait at the execution's single
place: the earliest ``queued_at`` of any wait it ever recorded, or the place of
an aborted shared walk it recovers (``qa_host_turn_inheritance``). Every line
therefore orders the same executions the same way. An unconsumed reservation
held by an execution still waiting for another host passes to an older live
waiter on its host (:func:`pass_to_older_waiter`), so the oldest set-waiter is
reserved each host in turn and no cycle of partial reservations can form. A
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
    """The order of a wait in every line; the SQL order of ``host_line``."""
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
    places = [parse_instant(row["place"])] if row is not None and row["place"] else []
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
        # Partial fixture schemas without the line hold no reservation.
        return None
    row = query_one(
        conn,
        "SELECT * FROM qa_test_machine_waits "
        f"WHERE claim_id={_p(conn)} AND state='reserved'",
        (claim.id,),
    )
    return dict(row) if row is not None else None


def pass_to_older_waiter(conn: Any, claim: Any) -> None:
    """Hand a partial set's reservation to an older live waiter on its host.

    The younger wait goes back to ``waiting`` at its own place before the
    reservation is released, so the release neither cancels it nor aborts its
    execution; the release then reserves the host for the line's head.
    """
    from yoke_core.domain.coordination_claims import release
    from yoke_core.domain.qa_host_turns import host_line

    holder = reserved_wait(conn, claim)
    if holder is None or not awaits_other_hosts(conn, holder):
        return
    line = host_line(conn, str(claim.target.test_machine))
    if not line or line_key(line[0]) >= line_key(holder):
        return
    conn.execute(
        "UPDATE qa_test_machine_waits SET state='waiting',claim_id=NULL "
        f"WHERE id={_p(conn)}",
        (str(holder["id"]),),
    )
    release(conn, claim.id, HOST_TURN_PASSED_REASON, commit=False)


def awaits_other_hosts(conn: Any, wait: Mapping[str, Any]) -> bool:
    """True while the wait's execution still waits for another host."""
    if not wait["qa_plan_execution_id"]:
        return False
    p = _p(conn)
    return (
        query_one(
            conn,
            "SELECT id FROM qa_test_machine_waits "
            f"WHERE qa_plan_execution_id={p} AND state='waiting' AND id<>{p}",
            (str(wait["qa_plan_execution_id"]), str(wait["id"])),
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
    commit: bool = True,
) -> dict:
    """Keep the cursor open and queue the execution on every host its case needs.

    Waits on hosts outside the set leave their lines; waits and reservations
    inside it keep them. Every new wait takes the execution's one place.
    """
    from yoke_core.domain.machine_qa_capability import host_claim_target
    from yoke_core.domain.qa_host_turns import (
        cancel_host_waits,
        host_wait_view,
        join_host_line,
        lock_host_turn,
        reserve_host_turn,
    )
    from yoke_core.domain.qa_plan_execution_lifecycle import finish_plan_execution

    execution_id = str(execution["id"])
    machines = sorted({test_machine, *test_machines})
    live = query_rows(
        conn,
        "SELECT DISTINCT test_machine FROM qa_test_machine_waits "
        f"WHERE qa_plan_execution_id={_p(conn)} AND state IN {_LIVE}",
        (execution_id,),
    )
    left = {str(row["test_machine"]) for row in live} - set(machines)
    for name in sorted(set(machines) | left):
        lock_host_turn(conn, host_claim_target(name))
    if left:
        cancel_host_waits(conn, execution_ids=[execution_id], test_machines=left)
    place = execution_place(conn, execution, machines) or utc_now()
    waits = [
        join_host_line(
            conn,
            host_claim_target(name),
            session_id=str(execution["session_id"]),
            actor_id=int(execution["actor_id"]),
            resume_command=f"yoke qa plan run --resume-execution-id {execution_id}",
            rationale=rationale
            if name == test_machine
            else f"held with {test_machine} for one case: {rationale}",
            execution_id=execution_id,
            queued_at=place,
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
    "pass_to_older_waiter",
    "record_host_wait",
    "require_host_set_turn",
    "reserved_wait",
]
