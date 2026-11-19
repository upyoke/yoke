"""Execution-owned host sets acquired together through each host's FIFO.

A case's set is its own hosts plus the union of its ``inherit`` chain's hosts.
Each chain baseline holds exactly its set: held hosts it does not need are
released, and a set the held hosts do not cover is released and acquired anew.
"""

from __future__ import annotations

from yoke_contracts.qa_case_starting_state import needs_test_machine

from typing import Any
from datetime import datetime

from yoke_core.domain.coordination_claims import get_claim, heartbeat, release
from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.machine_qa_case_hosts import case_machines
from yoke_core.domain.qa_plan_execution_store import marker

HOST_SET_REASON = "qa-plan-hosts:"


def execution_host_leases(conn: Any, execution: dict[str, Any]) -> list[Any]:
    """All active companion claims point back to their durable execution owner."""
    from yoke_core.domain.schema_common import _table_exists

    if not _table_exists(conn, "work_claims"):
        return []
    p = marker(conn)
    rows = query_rows(
        conn,
        f"SELECT id FROM work_claims WHERE reason={p} AND released_at IS NULL",
        (HOST_SET_REASON + str(execution["id"]),),
    )
    return sorted(
        (get_claim(conn, int(row["id"])) for row in rows),
        key=lambda claim: str(claim.target.test_machine),
    )


def heartbeat_execution_hosts(
    conn: Any, execution: dict[str, Any], *, now: datetime
) -> None:
    for claim in execution_host_leases(conn, execution):
        if claim.id != execution.get("test_machine_lease_id"):
            heartbeat(conn, claim.id, now=now, commit=False)


def release_execution_hosts(
    conn: Any, execution: dict[str, Any], *, reason: str
) -> None:
    """Release companions under sorted locks, leaving the primary to its owner."""
    from yoke_core.domain.qa_host_turns import lock_host_turn

    leases = execution_host_leases(conn, execution)
    for claim in leases:
        lock_host_turn(conn, claim.target)
    for claim in leases:
        if claim.id != execution.get("test_machine_lease_id"):
            release(conn, claim.id, reason, commit=False)


def require_case_host_leases(
    conn: Any, execution: dict[str, Any], case: dict[str, Any]
) -> None:
    """A running simultaneous case cannot continue after any host was released."""
    names = case_machines(case)
    if len(names) < 2:
        return
    from yoke_core.domain.machine_qa_execution_protocol import _validate_lease_owner

    leases = held_host_leases(conn, execution)
    if not set(names).issubset(leases):
        raise ValueError(
            "test_machine_set_lease_lost: this case no longer holds every declared "
            "machine; abort the execution and rerun its scoped QA command"
        )
    for name in names:
        _validate_lease_owner(
            conn,
            project=str(case["project"]),
            session_id=str(execution["session_id"]),
            actor_id=execution.get("actor_id"),
            lease_id=leases[name],
            allow_released=False,
        )


def begin_case_host_contract(
    conn: Any,
    execution: dict[str, Any],
    case: dict[str, Any],
    *,
    ordinal: int,
    test_machine: str | None,
    actor_id: str | None,
    session_id: str,
) -> Any:
    """Acquire the case's full sorted set, or acquire nothing and raise the
    first busy or unhealthy host for the caller to queue the whole set."""
    from yoke_core.domain.claim_chain_state import record_claim_reason
    from yoke_core.domain.machine_qa_case_machine import resolve_case_machine
    from yoke_core.domain.machine_qa_execution_protocol import (
        MachineQaProtocolLeaseHeld,
        _issue,
        begin_host_control_execution,
        commit_deferred_connection,
    )
    from yoke_core.domain.machine_qa_host_selection import (
        TestMachineFleetBusy,
        TestMachineHostUnhealthy,
        acquire_test_machine_admission,
    )
    from yoke_core.domain.machine_qa_plan_protocol import (
        continue_plan_host_control_execution,
        plan_case_contract_arguments,
    )
    from yoke_core.domain.qa_plan_execution_lifecycle import set_plan_machine_lease

    from yoke_core.domain.qa_resume_machine import execution_machine
    from yoke_core.domain.machine_qa_case_platform import (
        case_platform,
        matching_platform_hosts,
    )

    retained = execution_machine(conn, execution, case)
    if retained and test_machine and retained != test_machine:
        custody = (
            "active plan lease"
            if execution.get("test_machine_lease_id")
            else "recorded platform host"
        )
        raise ValueError(
            f"test_machine_constraint_mismatch: {custody} uses {retained!r}, "
            f"but --test-machine names {test_machine!r}; omit --test-machine to resume on its recorded host"
        )
    driver = resolve_case_machine(case, retained or test_machine)
    names = case_host_set(execution, case, ordinal, driver)
    lease_id = execution.get("test_machine_lease_id")
    from yoke_core.domain.qa_plan_execution_reentry import admitted_case

    primary = get_claim(conn, int(lease_id)).target.test_machine if lease_id else None
    held = held_hosts(conn, execution) if lease_id is not None else set()
    # A chain baseline not yet admitted takes exactly its set; an admitted
    # case continues only with the custody it was admitted with.
    baseline = (
        case.get("starting_state") != "inherit"
        and admitted_case(execution) != ordinal
    )
    if primary == driver and baseline and set(names) < held:
        release_hosts_outside(conn, execution, names)
    if lease_id is not None and (
        primary != driver or (baseline and not set(names) <= held)
    ):
        release_execution_hosts(conn, execution, reason="qa-case-host-change")
        release(conn, int(lease_id), "qa-case-host-change", commit=False)
        conn.execute(
            f"UPDATE qa_plan_executions SET test_machine_lease_id=NULL WHERE id={marker(conn)}",
            (str(execution["id"]),),
        )
        execution["test_machine_lease_id"] = None
    from yoke_core.domain.machine_qa_host_rows import test_machine_rows

    platforms = {}
    if any(case_machines(row) for row in execution["roster"]):
        platforms = {
            row.test_machine: row.settings["os"]
            for row in test_machine_rows(conn)
        }
    arguments = plan_case_contract_arguments(execution, case, ordinal=ordinal)
    deferred = commit_deferred_connection(conn)
    lease_id = execution.get("test_machine_lease_id")
    if len(names) < 2:
        if lease_id is None:
            contract = begin_host_control_execution(
                deferred,
                project=str(case["project"]),
                session_id=session_id,
                test_machine=driver,
                healthy_only=True,
                host_cases=[
                    row
                    for row in execution["roster"]
                    if needs_test_machine(row)
                    and case_platform(row, platforms) == case_platform(case, platforms)
                    and resolve_case_machine(row, None) in {None, driver}
                ],
                **arguments,
            )
            set_plan_machine_lease(conn, execution, lease_id=contract.lease_id)
            return contract
        return continue_plan_host_control_execution(
            conn,
            project=str(case["project"]),
            session_id=session_id,
            actor_id=actor_id,
            lease_id=int(lease_id),
            test_machine=driver,
            **{key: value for key, value in arguments.items() if key != "operation"},
        )

    if lease_id is not None:
        require_case_host_leases(
            conn,
            execution,
            {
                **case,
                "method_config": {
                    "test_machine": driver,
                    "test_machines": list(names),
                },
            },
        )
        return continue_plan_host_control_execution(
            conn,
            project=str(case["project"]),
            session_id=session_id,
            actor_id=actor_id,
            lease_id=int(lease_id),
            test_machine=driver,
            **{key: value for key, value in arguments.items() if key != "operation"},
        )

    from yoke_core.domain.machine_qa_capability import host_claim_target
    from yoke_core.domain.qa_host_set_turns import require_host_set_turn
    from yoke_core.domain.qa_host_turns import lock_host_turn

    # Lock in one fixed order and acquire only a set that is wholly free or
    # reserved for this execution; otherwise nothing is acquired and the
    # caller queues the execution on every host at its one place.
    for name in names:
        lock_host_turn(conn, host_claim_target(name))
    require_host_set_turn(conn, execution, names)
    admissions = {}
    try:
        for name in names:
            admission = acquire_test_machine_admission(
                deferred,
                project=str(case["project"]),
                session_id=session_id,
                test_machine=name,
                select_any=False,
                healthy_only=True,
                cases=(),
            )
            record_claim_reason(
                conn,
                claim_id=admission.lease.id,
                reason=HOST_SET_REASON + str(execution["id"]),
            )
            admissions[name] = admission
    except TestMachineFleetBusy as exc:
        release_execution_hosts(conn, execution, reason="qa-host-set-incomplete")
        held = exc.busy[0]
        raise MachineQaProtocolLeaseHeld(
            lease=held.lease, test_machine=held.test_machine, contention=held.contention
        ) from None
    except TestMachineHostUnhealthy:
        release_execution_hosts(conn, execution, reason="qa-host-set-incomplete")
        raise
    matching_platform_hosts(
        [admission.contract for admission in admissions.values()], (case,)
    )
    selected = admissions[driver]
    contract = _issue(
        conn,
        selected.contract,
        selected.lease,
        checks=(),
        selection_reason=selected.selection_reason,
        **arguments,
    )
    set_plan_machine_lease(conn, execution, lease_id=contract.lease_id)
    return contract


def case_host_set(
    execution: dict[str, Any], case: dict[str, Any], ordinal: int, driver: str | None
) -> tuple[str, ...]:
    """The case's hosts with its own ``inherit`` chain's union, sorted."""
    from yoke_core.domain.qa_plan_case_chain import ends_chain

    roster = execution["roster"]
    start = ordinal
    while start > 0 and not ends_chain(roster, start - 1):
        start -= 1
    end = ordinal
    while end < len(roster) - 1 and not ends_chain(roster, end):
        end += 1
    hosts = set(case_machines(case, driver))
    for row in roster[start : end + 1]:
        hosts.update(case_machines(row))
    return tuple(sorted(hosts))


def held_hosts(conn: Any, execution: dict[str, Any]) -> set[str]:
    """Hosts the execution holds: its primary lease and its companions."""
    return set(held_host_leases(conn, execution))


def held_host_leases(conn: Any, execution: dict[str, Any]) -> dict[str, int]:
    """Each active held host's lease id: the primary and its companions."""
    leases = {
        str(claim.target.test_machine): claim.id
        for claim in execution_host_leases(conn, execution)
    }
    lease_id = execution.get("test_machine_lease_id")
    if lease_id is not None:
        primary = get_claim(conn, int(lease_id))
        if primary.is_active:
            leases[str(primary.target.test_machine)] = primary.id
    return leases


def release_hosts_outside(
    conn: Any, execution: dict[str, Any], names: tuple[str, ...]
) -> None:
    """Release companions a new chain baseline no longer needs."""
    from yoke_core.domain.qa_host_turns import lock_host_turn

    extra = [
        claim
        for claim in execution_host_leases(conn, execution)
        if str(claim.target.test_machine) not in names
        and claim.id != execution.get("test_machine_lease_id")
    ]
    for claim in extra:
        lock_host_turn(conn, claim.target)
    for claim in extra:
        release(conn, claim.id, "qa-case-host-set-shrunk", commit=False)
