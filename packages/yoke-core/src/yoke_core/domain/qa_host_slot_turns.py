"""One Test Machine per OS slot of a simultaneous-host case.

A slotted case lists OS slots in ``method_config.test_machines`` and maps a
slot OS to its tags in ``capability_tags``. Slots of the driver's OS also carry
the tags of cases inheriting the driver host. A slot's eligible hosts are the
registered hosts of its OS carrying its tags with a verification result, so
slots of one OS share one eligible set. Failed verification can block a wait.
Slots take hosts in order, each the lowest-named available host no earlier
slot took.

While it waits, each slot is one any-of need at the execution's one queue
place. One host carries one live wait per execution, so the eligible hosts of
an OS are dealt round-robin across that OS's slots. A free host never serves
a slotted waiter alone: :func:`assign_slot_hosts` reserves a host for every
slot at once, or nothing, and the host passes to the next waiter.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Collection, Iterable, Mapping, Sequence
from typing import Any

from yoke_contracts.machine_config.test_machine import (
    TestMachineCapabilityError,
    test_machine_capability_tags,
)
from yoke_core.domain.db_helpers import instant_parameter, query_one, query_rows
from yoke_core.domain.machine_qa_execution_protocol import MachineQaProtocolError
from yoke_core.domain.qa_plan_execution_store import marker as _p

TEST_MACHINE_SLOTS_UNAVAILABLE = "test_machine_slots_unavailable"

#: Each slot's OS and the names of its eligible hosts, in slot order.
SlotEligibility = tuple[tuple[str, tuple[str, ...]], ...]


class TestMachineSlotsBusy(MachineQaProtocolError):
    """Some OS has too few available hosts; the case queues one need per slot."""

    def __init__(
        self, slots: tuple[tuple[str, ...], ...], rationale: str, test_machine: str
    ) -> None:
        super().__init__(rationale)
        #: Per slot, the hosts its need waits on; no host is in two slots.
        self.slots = slots
        self.test_machine = test_machine


def _failed_verifications(conn: Any) -> set[str]:
    """Names whose current verification failed, even when verified_at is unset."""
    return {
        str(row["name"])
        for row in query_rows(
            conn,
            "SELECT m.name FROM test_machines m "
            "JOIN test_machine_verifications v ON v.test_machine_id=m.id "
            "WHERE v.status='error' AND v.checked_at IS NOT NULL",
        )
    }


def slot_eligibility(
    conn: Any,
    case: Mapping[str, Any],
    cases: Sequence[Mapping[str, Any]],
    *,
    failed_verifications: Collection[str] = (),
) -> SlotEligibility:
    """Each slot of *case* with its eligible hosts under its OS's tags.

    Queue admission can include hosts with failed verification so it can wait
    for their recovery. Refuses when too few matching hosts have a result.
    """
    from yoke_core.domain.machine_qa_case_hosts import (
        case_slots,
        driver_slot_os,
        slot_os_tags,
    )
    from yoke_core.domain.machine_qa_case_platform import required_host_tags
    from yoke_core.domain.machine_qa_host_rows import test_machine_rows

    driver_os = driver_slot_os(case)
    rows = test_machine_rows(conn)
    slots = [slot["os"] for slot in case_slots(case)]
    eligibility = []
    for os_name in slots:
        tags = (
            required_host_tags(cases)
            if os_name == driver_os
            else slot_os_tags(case, os_name)
        )
        names = tuple(
            row.test_machine
            for row in rows
            if row.settings["os"] == os_name
            and (row.verified_at is not None or row.test_machine in failed_verifications)
            and tags.issubset(test_machine_capability_tags(row.settings))
        )
        needed = slots.count(os_name)
        if len(names) < needed:
            key = case.get("case_key") or case.get("requirement_id") or "unknown"
            tagged = f" carrying {', '.join(sorted(tags))}" if tags else ""
            raise TestMachineCapabilityError(
                f"{TEST_MACHINE_SLOTS_UNAVAILABLE}: case {key!r} needs {needed} "
                f"verified {os_name} Test Machines{tagged} at once, but only "
                f"{len(names)} matching hosts are registered ({', '.join(names) or 'none'}); "
                "register and verify another matching Test Machine with `yoke "
                "test-machine verify --test-machine NAME`, or rewrite the case's "
                "method_config.test_machines slots"
            )
        eligibility.append((os_name, names))
    return tuple(eligibility)


def pick_slot_hosts(
    eligibility: SlotEligibility, available: Iterable[str]
) -> tuple[str, ...] | None:
    """One distinct host per slot from *available*, in its order, or None."""
    ordered = list(available)
    taken: list[str] = []
    for _os, names in eligibility:
        host = next((n for n in ordered if n in names and n not in taken), None)
        if host is None:
            return None
        taken.append(host)
    return tuple(taken)


def slot_waits(eligibility: SlotEligibility) -> tuple[tuple[str, ...], ...]:
    """Deal each OS's eligible hosts round-robin across that OS's slots."""
    waits: list[list[str]] = [[] for _ in eligibility]
    for os_name in {os_name for os_name, _ in eligibility}:
        indices = [i for i, (slot_os, _) in enumerate(eligibility) if slot_os == os_name]
        for position, name in enumerate(eligibility[indices[0]][1]):
            waits[indices[position % len(indices)]].append(name)
    return tuple(tuple(names) for names in waits)


def _unavailable(conn: Any, name: str) -> str | None:
    from yoke_core.domain.coordination_claims import active_claim
    from yoke_core.domain.machine_qa_capability import host_claim_target
    from yoke_core.domain.qa_host_health import host_unhealthy, unhealthy_rationale

    claim = active_claim(conn, host_claim_target(name))
    if claim is not None:
        return f"lease {claim.id} held by {claim.session_id}"
    health = host_unhealthy(conn, name)
    return unhealthy_rationale(health) if health is not None else None


def select_slot_hosts(
    conn: Any,
    execution: Mapping[str, Any],
    case: Mapping[str, Any],
    cases: Sequence[Mapping[str, Any]],
) -> tuple[str, tuple[str, ...], tuple[tuple[str, ...], ...]]:
    """Admit *case*'s slots: the driver, every host, and the waits it queues.

    A host is available while free and healthy, reserved for this execution,
    or held by it; held and reserved hosts are taken first.
    """
    from yoke_core.domain.machine_qa_case_hosts import case_slots
    from yoke_core.domain.qa_host_set_turns import execution_waits
    from yoke_core.domain.qa_plan_host_leases import held_hosts

    eligibility = slot_eligibility(
        conn, case, cases, failed_verifications=_failed_verifications(conn),
    )
    waits = slot_waits(eligibility)
    held = held_hosts(conn, execution)
    reserved = {
        str(wait["test_machine"])
        for wait in execution_waits(conn, str(execution["id"]))
        if wait["state"] == "reserved"
    }
    names = sorted({name for _, hosts in eligibility for name in hosts})
    unavailable = {
        name: reason
        for name in names
        if name not in held and name not in reserved
        if (reason := _unavailable(conn, name)) is not None
    }
    available = sorted(
        (name for name in names if name not in unavailable),
        key=lambda n: (n not in held, n not in reserved, n),
    )
    picked = pick_slot_hosts(eligibility, available)
    if picked is None:
        slot_oses = [os_name for os_name, _ in eligibility]
        needed = Counter(slot_oses)
        clauses = [f"no available host for every OS slot ({', '.join(slot_oses)})"]
        blocked_hosts = []
        for os_name, hosts in dict(eligibility).items():
            blocked = [name for name in hosts if name in unavailable]
            if len(hosts) - len(blocked) < needed[os_name]:
                reasons = "; ".join(f"{name}: {unavailable[name]}" for name in blocked)
                clauses.append(f"{os_name} slot waits on {reasons}")
                blocked_hosts.extend(blocked)
        clauses.append(f"free now: {', '.join(available) or 'none'}")
        raise TestMachineSlotsBusy(waits, "; ".join(clauses), blocked_hosts[0])
    driver = next(i for i, slot in enumerate(case_slots(case)) if slot.get("driver"))
    return picked[driver], tuple(sorted(picked)), waits


def slotted_wait(conn: Any, wait: Mapping[str, Any]) -> bool:
    """The wait is one slot need of an execution waiting on several."""
    if not wait.get("need_id") or not wait.get("qa_plan_execution_id"):
        return False
    row = query_one(
        conn,
        "SELECT COUNT(DISTINCT need_id) AS needs FROM qa_test_machine_waits "
        f"WHERE qa_plan_execution_id={_p(conn)} AND state IN ('waiting','reserved') "
        "AND need_id IS NOT NULL",
        (str(wait["qa_plan_execution_id"]),),
    )
    return row is not None and int(row["needs"]) > 1


def assign_slot_hosts(conn: Any, execution: Mapping[str, Any]) -> bool:
    """Reserve one free host per slot need of *execution* at once, or none.

    Each need's OS is its hosts' OS; a slot may take any waited-on host of
    its OS. Every reservation is taken in one savepoint, the execution's
    other waits settle, and the execution is woken once.
    """
    from yoke_contracts.timestamps import utc_now
    from yoke_core.domain.coordination_claims import acquire
    from yoke_core.domain.db_savepoint import savepoint
    from yoke_core.domain.machine_qa_capability import host_claim_target
    from yoke_core.domain.machine_qa_host_rows import test_machine_rows
    from yoke_core.domain.qa_host_set_turns import execution_waits
    from yoke_core.domain.qa_host_turns import HOST_TURN_REASON, _wake_waiter

    execution_id = str(execution["id"])
    waits = {
        str(wait["test_machine"]): wait
        for wait in execution_waits(conn, execution_id)
        if wait["state"] == "waiting" and wait["need_id"]
    }
    failed_verifications = _failed_verifications(conn)
    oses = {
        row.test_machine: row.settings["os"]
        for row in test_machine_rows(conn)
        if row.verified_at is not None or row.test_machine in failed_verifications
    }
    needs: dict[str, set[str]] = {}
    for name, wait in waits.items():
        needs.setdefault(str(wait["need_id"]), set())
        if name in oses:
            needs[str(wait["need_id"])].add(oses[name])
    if any(len(need) != 1 for need in needs.values()):
        return False
    slots = sorted(next(iter(need)) for need in needs.values())
    eligibility = tuple(
        (os_name, tuple(sorted(n for n in waits if oses.get(n) == os_name)))
        for os_name in slots
    )
    available = sorted(name for name in waits if _unavailable(conn, name) is None)
    picked = pick_slot_hosts(eligibility, available)
    if picked is None:
        return False
    p = _p(conn)
    with savepoint(conn, "qa_assign_slot_hosts", owns=False):
        for name in picked:
            wait = waits[name]
            claim = acquire(
                conn,
                host_claim_target(name),
                str(wait["session_id"]),
                reason=HOST_TURN_REASON + str(wait["id"]),
                commit=False,
            )
            conn.execute(
                f"UPDATE qa_test_machine_waits SET state='reserved',claim_id={p} WHERE id={p}",
                (claim.id, str(wait["id"])),
            )
        conn.execute(
            f"UPDATE qa_test_machine_waits SET state='cancelled',settled_at={p} "
            f"WHERE qa_plan_execution_id={p} AND state='waiting'",
            (instant_parameter(conn, utc_now()), execution_id),
        )
    _wake_waiter(conn, waits[picked[-1]], claim)
    return True


def front_waiter(conn: Any, target: Any) -> dict[str, Any] | None:
    """The waiter a free host is reserved for; slotted sets take all at once."""
    from yoke_core.domain.coordination_claims import active_claim
    from yoke_core.domain.qa_host_idle_waiters import serving_waiters
    from yoke_core.domain.qa_host_set_turns import set_at_front

    for wait in serving_waiters(conn, target.test_machine):
        if not set_at_front(conn, wait):
            continue
        if not slotted_wait(conn, wait):
            return wait
        if assign_slot_hosts(conn, {"id": wait["qa_plan_execution_id"]}):
            if active_claim(conn, target) is not None:
                return None
            return front_waiter(conn, target)
    return None


__all__ = [
    "TEST_MACHINE_SLOTS_UNAVAILABLE",
    "TestMachineSlotsBusy",
    "assign_slot_hosts",
    "front_waiter",
    "pick_slot_hosts",
    "select_slot_hosts",
    "slot_eligibility",
    "slot_waits",
    "slotted_wait",
]
