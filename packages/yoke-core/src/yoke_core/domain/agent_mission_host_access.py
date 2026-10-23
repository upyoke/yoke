"""Select a mission's driver or a declared companion under its retained lease."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.machine_qa_case_hosts import case_machines
from yoke_core.domain.machine_qa_execution_protocol import _issue, _validate_lease_owner
from yoke_core.domain.machine_qa_plan_protocol import (
    continue_plan_host_control_execution,
    plan_case_contract_arguments,
)
from yoke_core.domain.qa_plan_host_leases import (
    execution_host_leases,
    require_case_host_leases,
)


def mission_host_contract(
    conn: Any,
    execution: dict,
    case: dict,
    *,
    ordinal: int,
    actor: Any,
    test_machine: str | None,
) -> Any:
    """Validate the whole host set before issuing authority for one host."""
    require_case_host_leases(conn, execution, case)
    driver_lease, _ = _validate_lease_owner(
        conn,
        project=str(case["project"]),
        session_id=actor.session_id,
        actor_id=actor.actor_id,
        lease_id=int(execution["test_machine_lease_id"]),
        allow_released=False,
    )
    driver = str(driver_lease.target.test_machine)
    selected = test_machine if test_machine is not None else driver
    if selected == driver:
        arguments = plan_case_contract_arguments(execution, case, ordinal=ordinal)
        return continue_plan_host_control_execution(
            conn,
            project=str(case["project"]),
            session_id=actor.session_id,
            actor_id=actor.actor_id,
            lease_id=driver_lease.id,
            **{key: value for key, value in arguments.items() if key != "operation"},
        )
    if selected not in case_machines(case):
        raise ValueError(
            f"mission_machine_not_declared: {selected!r} is outside this case's "
            f"host set; omit --test-machine for driver {driver!r} or name one of "
            f"{', '.join(case_machines(case))}"
        )
    lease = next(
        (
            claim
            for claim in execution_host_leases(conn, execution)
            if str(claim.target.test_machine) == selected
        ),
        None,
    )
    if lease is None:
        raise ValueError(
            f"test_machine_set_lease_lost: no retained lease for {selected!r}; "
            "abort the execution and rerun its scoped QA command"
        )
    lease, candidate = _validate_lease_owner(
        conn,
        project=str(case["project"]),
        session_id=actor.session_id,
        actor_id=actor.actor_id,
        lease_id=lease.id,
        allow_released=False,
    )
    contract = _issue(
        conn,
        candidate,
        lease,
        operation="host_command",
        checks=(),
        baselines=(),
        cases=(),
    )
    from yoke_core.domain.machine_reset_debt import record_reset_owed

    # Persist before authority leaves the server: even a failed command can
    # mutate the companion, and driver teardown cannot prove its restoration.
    record_reset_owed(
        conn,
        case=case,
        test_machine=selected,
        lease_id=lease.id,
        contract_digest=contract.contract_digest,
    )
    return contract
