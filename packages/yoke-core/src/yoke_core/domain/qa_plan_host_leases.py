"""Execution-owned host sets acquired together through each host FIFO."""

from __future__ import annotations

from yoke_contracts.machine_config.test_machine import test_machine_capability_tags

from typing import Any
from datetime import datetime

from yoke_core.domain.coordination_claims import get_claim, heartbeat, release
from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.machine_qa_case_hosts import case_machines
from yoke_core.domain.qa_plan_execution_store import marker

from yoke_core.domain.qa_case_host_custody import HOST_SET_REASON, bind_case_host


def execution_host_leases(conn: Any, execution: dict[str, Any]) -> list[Any]:
    """Read all active host claims naming this durable execution."""
    from yoke_core.domain.schema_common import _table_exists

    if not _table_exists(conn, "work_claims"):
        return []
    p = marker(conn)
    prefix = HOST_SET_REASON + str(execution["id"])
    rows = query_rows(
        conn,
        f"SELECT id FROM work_claims WHERE (reason={p} OR reason LIKE {p}) AND released_at IS NULL",
        (prefix, prefix + ":%"),
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
        require_host_tags,
        required_host_tags,
    )

    from yoke_core.domain.qa_mixed_host_set import mixed_mission_host_set

    chain = host_case_chain(execution, ordinal)
    mixed = mixed_mission_host_set(conn, execution, ordinal, test_machine)
    if mixed:
        driver, names = mixed
    else:
        explicit = resolve_case_machine(case, test_machine)
        driver = explicit or execution_machine(conn, execution, case)
        tags = required_host_tags(chain)
        if tags and driver and not explicit:
            from yoke_core.domain.machine_qa_host_rows import test_machine_rows

            settings = {row.test_machine: row.settings for row in test_machine_rows(conn)}
            if not tags.issubset(test_machine_capability_tags(settings[driver])):
                driver = None
        names = tuple(sorted(set(case_machines(case, driver)).union(
            name for row in chain for name in case_machines(row)
        )))
    lease_id = execution.get("test_machine_lease_id")
    from yoke_core.domain.qa_plan_execution_reentry import admitted_case

    lease = get_claim(conn, int(lease_id)) if lease_id else None
    primary = lease.target.test_machine if lease and lease.is_active else None
    held = held_hosts(conn, execution) if lease_id is not None else set()
    # A chain baseline not yet admitted takes exactly its set; an admitted
    # case continues only with the custody it was admitted with.
    baseline = (
        case.get("starting_state") != "inherit"
        and admitted_case(execution) != ordinal
    )
    if primary and not baseline and primary != driver and not mixed:
        raise ValueError(
            f"test_machine_constraint_mismatch: active plan lease uses {primary!r}; "
            "finish or abort this execution to restore the host before switching machines"
        )
    if not mixed and primary == driver and baseline and set(names) < held:
        release_hosts_outside(conn, execution, names)
    if not mixed and lease_id is not None and (
        primary is None or primary != driver or (baseline and not set(names) <= held)
    ):
        release_execution_hosts(conn, execution, reason="qa-case-chain-ended")
        release(conn, int(lease_id), "qa-case-chain-ended", commit=False)
        conn.execute(
            f"UPDATE qa_plan_executions SET test_machine_lease_id=NULL WHERE id={marker(conn)}",
            (str(execution["id"]),),
        )
        execution["test_machine_lease_id"] = None
    arguments = plan_case_contract_arguments(execution, case, ordinal=ordinal)
    deferred = commit_deferred_connection(conn)
    lease_id = execution.get("test_machine_lease_id")
    leases = held_host_leases(conn, execution)
    if lease_id is not None and len(names) > 1 and not mixed:
        require_case_host_leases(
            conn, execution,
            {**case, "method_config": {"test_machine": driver, "test_machines": list(names)}},
        )
    selection_reason = None
    if len(names) < 2 and not mixed and lease_id is None:
        contract = begin_host_control_execution(
            deferred,
            project=str(case["project"]),
            session_id=session_id,
            test_machine=driver,
            healthy_only=True,
            host_cases=chain,
            **arguments,
        )
    else:
        from yoke_core.domain.machine_qa_capability import host_claim_target
        from yoke_core.domain.qa_host_set_turns import require_host_set_turn
        from yoke_core.domain.qa_host_turns import lock_host_turn
        from yoke_core.domain.db_savepoint import savepoint

        with savepoint(conn, "qa_case_host_set", owns=False):
            if not set(names) <= leases.keys():
                all_names = tuple(sorted(set(names) | leases.keys()))
                for name in all_names:
                    lock_host_turn(conn, host_claim_target(name))
                try:
                    require_host_set_turn(conn, execution, all_names, held_leases=leases)
                    for name in names:
                        if name in leases:
                            continue
                        admission = acquire_test_machine_admission(
                            deferred, project=str(case["project"]), session_id=session_id,
                            test_machine=name, select_any=False, healthy_only=True, cases=(),
                        )
                        record_claim_reason(
                            conn, claim_id=admission.lease.id,
                            reason=HOST_SET_REASON + str(execution["id"]),
                        )
                        leases[name] = admission.lease.id
                        if name == driver:
                            selection_reason = admission.selection_reason
                except (MachineQaProtocolLeaseHeld, TestMachineHostUnhealthy) as exc:
                    if mixed and held:
                        raise ValueError(
                            "qa_open_walk_host_set_changed: finish the open walks on their "
                            "retained hosts, then restart with the full host set available"
                        ) from exc
                    raise
                except TestMachineFleetBusy as exc:
                    busy = exc.busy[0]
                    raise MachineQaProtocolLeaseHeld(
                        lease=busy.lease, test_machine=busy.test_machine,
                        contention=busy.contention, test_machines=all_names,
                    ) from None

            contract = continue_plan_host_control_execution(
                conn, project=str(case["project"]), session_id=session_id,
                actor_id=actor_id, lease_id=leases[driver] if driver in leases else int(lease_id),
                test_machine=driver, selection_reason=selection_reason,
                **{key: value for key, value in arguments.items() if key != "operation"},
            )
            require_host_tags(contract.settings, chain)
    bind_case_host(conn, execution, case, contract.lease_id)
    for name in case_machines(case):
        if name in leases and leases[name] != contract.lease_id:
            bind_case_host(conn, execution, case, leases[name], companion=True)
    set_plan_machine_lease(conn, execution, lease_id=contract.lease_id)
    return contract


def host_case_chain(
    execution: dict[str, Any], ordinal: int
) -> list[dict[str, Any]]:
    """Return the baseline case and its inheriting cases."""
    from yoke_core.domain.qa_plan_case_chain import ends_chain

    roster = execution["roster"]
    start = ordinal
    while start > 0 and not ends_chain(roster, start - 1):
        start -= 1
    end = ordinal
    while end < len(roster) - 1 and not ends_chain(roster, end):
        end += 1
    return roster[start : end + 1]


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
            leases[str(primary.target.test_machine)] = int(lease_id)
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
