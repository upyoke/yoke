"""Deterministic admission selection across a project's QA machines."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from yoke_contracts.machine_config.test_machine import TestMachineCapabilityError

from yoke_core.domain.coordination_claim_contention import ClaimContention
from yoke_core.domain.coordination_claim_record import CoordinationClaim
from yoke_core.domain.coordination_claims import (
    CoordinationClaimHeldError,
    active_claim,
    acquire,
)
from yoke_core.domain.host_control_runner import (
    TestMachineContract,
    list_test_machine_contracts,
    load_test_machine_contract,
)
from yoke_core.domain.machine_qa_capability import host_claim_target


@dataclass(frozen=True)
class BusyTestMachine:
    """One candidate whose global host claim is already held."""

    machine: str
    lease: CoordinationClaim
    contention: ClaimContention | None


class TestMachineFleetBusy(TestMachineCapabilityError):
    """Every eligible machine is already admitted to another execution."""

    def __init__(self, busy: list[BusyTestMachine]) -> None:
        names = ", ".join(candidate.machine for candidate in busy)
        super().__init__(f"all registered test machines are in use: {names}")
        self.busy = tuple(busy)


def acquire_test_machine(
    conn: Any,
    *,
    project: str,
    session_id: str,
    machine: str | None,
    select_any: bool,
) -> tuple[TestMachineContract, CoordinationClaim]:
    """Acquire the named host, or the first free host in stable name order."""
    if machine is not None or not select_any:
        candidates = [
            load_test_machine_contract(conn, project=project, machine=machine)
        ]
    else:
        candidates = list_test_machine_contracts(conn, project=project)
        if not candidates:
            raise TestMachineCapabilityError(
                f"project {project!r} has no test-machine capability"
            )
    busy: list[BusyTestMachine] = []
    for candidate in candidates:
        name = candidate.settings["resource_name"]
        target = host_claim_target(name)
        try:
            lease = acquire(
                conn,
                target,
                session_id,
                reason="machine-qa-execution",
            )
        except CoordinationClaimHeldError as exc:
            held = active_claim(conn, target)
            if held is None:
                raise TestMachineCapabilityError(
                    "test-machine lease changed while acquiring; retry execution"
                ) from None
            busy.append(BusyTestMachine(name, held, exc.contention))
            continue
        return candidate, lease
    raise TestMachineFleetBusy(busy)


__all__ = [
    "BusyTestMachine",
    "TestMachineFleetBusy",
    "acquire_test_machine",
]
