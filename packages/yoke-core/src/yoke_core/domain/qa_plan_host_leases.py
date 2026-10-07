"""Execution-owned host sets acquired together through each host's FIFO."""

from __future__ import annotations

from typing import Any

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
        key=lambda claim: str(claim.target.machine_id),
    )


def heartbeat_execution_hosts(
    conn: Any, execution: dict[str, Any], *, now: str
) -> None:
    for claim in execution_host_leases(conn, execution):
        if claim.id != execution.get("machine_lease_id"):
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
        if claim.id != execution.get("machine_lease_id"):
            release(conn, claim.id, reason, commit=False)


def require_case_host_leases(
    conn: Any, execution: dict[str, Any], case: dict[str, Any]
) -> None:
    """A running simultaneous case cannot continue after any host was released."""
    names = case_machines(case)
    if len(names) < 2:
        return
    from yoke_core.domain.machine_qa_execution_protocol import _validate_lease_owner

    leases = {
        str(claim.target.machine_id): claim
        for claim in execution_host_leases(conn, execution)
    }
    if set(leases) != set(names):
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
            lease_id=leases[name].id,
            allow_released=False,
        )


def begin_case_host_contract(
    conn: Any,
    execution: dict[str, Any],
    case: dict[str, Any],
    *,
    ordinal: int,
    machine: str | None,
    actor_id: str | None,
    session_id: str,
) -> Any:
    """Acquire a full sorted set or release the partial set and queue the busy host."""
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
        acquire_test_machine_admission,
    )
    from yoke_core.domain.machine_qa_plan_protocol import (
        continue_plan_host_control_execution,
        plan_case_contract_arguments,
    )
    from yoke_core.domain.qa_plan_execution_lifecycle import set_plan_machine_lease

    driver = resolve_case_machine(case, machine)
    names = case_machines(case, machine)
    arguments = plan_case_contract_arguments(execution, case, ordinal=ordinal)
    deferred = commit_deferred_connection(conn)
    lease_id = execution.get("machine_lease_id")
    if len(names) < 2:
        if lease_id is None:
            contract = begin_host_control_execution(
                deferred,
                project=str(case["project"]),
                session_id=session_id,
                machine=driver,
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
            machine=driver,
            **{key: value for key, value in arguments.items() if key != "operation"},
        )

    if lease_id is not None:
        require_case_host_leases(conn, execution, case)
        return continue_plan_host_control_execution(
            conn,
            project=str(case["project"]),
            session_id=session_id,
            actor_id=actor_id,
            lease_id=int(lease_id),
            machine=driver,
            **{key: value for key, value in arguments.items() if key != "operation"},
        )

    from yoke_core.domain.machine_qa_capability import host_claim_target
    from yoke_core.domain.qa_host_turns import lock_host_turn

    # Lock and acquire in the same fixed order. On contention no partial set
    # remains held, so opposite driving hosts cannot form a hold-and-wait cycle.
    for name in names:
        lock_host_turn(conn, host_claim_target(name))
    admissions = {}
    try:
        for name in names:
            admission = acquire_test_machine_admission(
                deferred,
                project=str(case["project"]),
                session_id=session_id,
                machine=name,
                select_any=False,
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
            lease=held.lease, machine=held.machine, contention=held.contention
        ) from None
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
