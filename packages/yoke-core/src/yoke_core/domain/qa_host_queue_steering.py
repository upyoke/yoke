"""Steering edits to the shared Test Machine queue under its transaction lock."""

from datetime import timedelta

from yoke_contracts.refusal_recovery import compose_refusal
from yoke_contracts.timestamps import utc_now
from yoke_core.domain.db_helpers import instant_parameter
from yoke_core.domain.qa_host_idle_waiters import recheck_host_sets, serving_waiters
from yoke_core.domain.qa_host_queue import machine_waiters, queue_waits
from yoke_core.domain.qa_host_set_turns import (
    HOST_TURN_PASSED_REASON,
    execution_waits,
    line_key,
    reserved_wait,
    return_reservations,
    set_at_front,
)
from yoke_core.domain.qa_host_turn_borrow import turn_in_operation
from yoke_core.domain.qa_host_turns import host_wait_view, reserve_host_turn
from yoke_core.domain.qa_plan_execution_store import marker as _p
from yoke_core.domain.work_claim_targets import make_qa_admission_target

_TICK = timedelta(microseconds=1)


class QueueEditRefused(ValueError):
    def __init__(self, code: str, reason: str, recovery: str):
        super().__init__(compose_refusal(reason, recovery=recovery))
        self.code = code


def _wait_on(conn, execution, host):
    from yoke_core.domain.qa_plan_host_leases import held_host_leases

    if host in held_host_leases(conn, execution):
        raise QueueEditRefused(
            "qa_host_turn_started",
            f"Execution {execution['id']} has started using {host}",
            "Wait for that execution to finish using the host before editing its queue",
        )
    waits = execution_waits(conn, str(execution["id"]))
    wait = next((row for row in waits if row["test_machine"] == host), None)
    if wait is None or execution["state"] != "waiting":
        raise QueueEditRefused(
            "qa_host_turn_not_waiting",
            f"Execution {execution['id']} has no waiting or reserved turn on {host}",
            "Read the steering fleet report and retry with a current waiter on this host",
        )
    return wait, waits


def _write_execution_place(conn, execution_id, place):
    p = _p(conn)
    conn.execute(
        f"UPDATE qa_test_machine_waits SET queued_at={p} WHERE qa_plan_execution_id={p}",
        (instant_parameter(conn, place), str(execution_id)),
    )


def _move_before(conn, wait, anchor):
    """Allocate a durable instant between two queue places.

    If the adjacent places share a timestamp or are one microsecond apart,
    shift the smallest necessary prefix back by microseconds, preserving
    its order on every host. A walk's historical waits share its new place
    so requeueing a different host or resuming cannot restore the old rank.
    """
    execution_id = wait["qa_plan_execution_id"]
    rows = queue_waits(conn, include_reserved=True)
    if anchor is None:
        place = max((line_key(row)[0] for row in rows), default=utc_now()) + _TICK
    else:
        cutoff = line_key(anchor)[:2]
        before = {
            line_key(row)[:2]: row
            for row in rows
            if (row["state"] == "waiting" or row["qa_plan_execution_id"])
            and row["qa_plan_execution_id"] != execution_id
            and line_key(row)[:2] < cutoff
        }
        place = cutoff[0] - _TICK
        current = place
        for (clock, _owner), row in sorted(before.items(), reverse=True):
            if clock < current:
                break
            current -= _TICK
            if row["qa_plan_execution_id"]:
                _write_execution_place(conn, row["qa_plan_execution_id"], current)
            else:
                p = _p(conn)
                conn.execute(
                    f"UPDATE qa_test_machine_waits SET queued_at={p} WHERE id={p}",
                    (instant_parameter(conn, current), str(row["id"])),
                )
    _write_execution_place(conn, execution_id, place)


def _serve_hosts(conn, waits):
    machines = sorted({str(wait["test_machine"]) for wait in waits})
    recheck_host_sets(conn, machines)
    for machine in machines:
        reserve_host_turn(conn, make_qa_admission_target(machine))


def place_waiter(conn, execution, host: str, position: int) -> dict:
    """Place the execution before the Nth waiter, or after the line."""
    from yoke_core.domain.coordination_claims import active_claim

    wait, waits = _wait_on(conn, execution, host)
    waiting = machine_waiters(conn, host)
    if wait["state"] == "waiting" and not any(
        row["id"] == wait["id"] for row in waiting
    ):
        raise QueueEditRefused(
            "qa_host_turn_not_waiting",
            f"Execution {execution['id']} already reserved another host that serves the same need",
            "Use the host it reserved or choose a waiter that can take this host",
        )
    claim = active_claim(conn, make_qa_admission_target(host))
    reservation = reserved_wait(conn, claim) if claim else None
    line = ([reservation] if reservation else []) + waiting
    anchor = line[position - 1] if position <= len(line) else None
    if anchor is None or anchor["id"] != wait["id"]:
        # The current turn already has custody. The first waiting row is also
        # an upper bound when an older walk joined after that turn was reserved.
        if reservation and anchor is reservation and len(line) > 1:
            anchor = min(line[:2], key=line_key)
        _move_before(conn, wait, anchor)
        _serve_hosts(conn, waits)
    return {
        "execution_id": str(execution["id"]),
        "host": host,
        "position": host_wait_view(conn, wait["id"])["position"],
    }


def hand_over(conn, holder, receiver, host: str) -> dict:
    """Give an unstarted turn to another execution without settling either wait."""
    from yoke_core.domain.coordination_claims import active_claim

    source, source_waits = _wait_on(conn, holder, host)
    destination, destination_waits = _wait_on(conn, receiver, host)
    target = make_qa_admission_target(host)
    claim = active_claim(conn, target)
    if (
        source["state"] != "reserved"
        or destination["state"] != "waiting"
        or claim is None
        or claim.id != source["claim_id"]
        or not any(
            row["id"] == destination["id"] for row in serving_waiters(conn, host)
        )
    ):
        raise QueueEditRefused(
            "qa_host_turn_handover_unavailable",
            f"{host} needs a reserved holder and an eligible waiting receiver",
            "Check the steering fleet report and retry with the current holder and waiter",
        )
    if turn_in_operation(claim):
        raise QueueEditRefused(
            "qa_host_turn_operation_running",
            f"A host operation is running on the reservation for {host}",
            "Wait for the operation to finish or have its owner abort it, then retry",
        )
    # Qualify the receiver at its current place on every other host before
    # bringing it to the front of this host.
    if not set_at_front(conn, destination, exclude_host=host):
        raise QueueEditRefused(
            "qa_host_turn_receiver_blocked",
            f"Execution {receiver['id']} has an earlier waiter on another required host",
            "Wait until it reaches the front on each other host, then retry",
        )
    anchor = min(
        [
            source,
            *(
                row
                for row in machine_waiters(conn, host)
                if row["id"] != destination["id"]
            ),
        ],
        key=line_key,
    )
    _move_before(conn, destination, anchor)
    return_reservations(conn, [source], HOST_TURN_PASSED_REASON)
    new_claim = active_claim(conn, target)
    new_wait = reserved_wait(conn, new_claim) if new_claim else None
    if new_wait is None or new_wait["id"] != destination["id"]:
        raise QueueEditRefused(
            "qa_host_turn_receiver_unserved",
            f"{host} could not reserve a turn for execution {receiver['id']}",
            "Check the host health and both waits in the steering fleet report before retrying",
        )
    _serve_hosts(conn, [*source_waits, *destination_waits])
    return {
        "execution_id": str(receiver["id"]),
        "prior_execution_id": str(holder["id"]),
        "host": host,
        "position": 1,
    }
