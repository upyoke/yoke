"""One operation contract, one implementation per kind of host.

Every operator-run test-machine operation -- verify, reset, capture a golden
baseline, diagnose the terminal bridge -- is expressed once here as a contract,
and each kind of host implements it. The kind is declared on the machine's own
settings rather than inferred, so adding a kind is a new implementation plus a
new enum value: no command, function id, handler, or receipt shape changes.
"""

from __future__ import annotations

from typing import Callable, Protocol, Sequence

from yoke_contracts.machine_config.test_machine import (
    MAC_SSH_HOST_KIND,
    TestMachineCapabilityError,
    validate_test_machine_host_kind,
)
from yoke_contracts.machine_qa_execution import HostControlExecutionContract
from yoke_harness.test_machine_types import HostActionResult


class HostOperations(Protocol):
    """What every kind of test machine must be able to do."""

    secret_values: Sequence[str]

    def check_connection(self) -> HostActionResult: ...

    def check_terminal_bridge(self) -> HostActionResult: ...

    def diagnose_terminal_bridge(self) -> HostActionResult: ...

    def reach_baseline(self, name: str) -> HostActionResult: ...

    def capture_golden_baseline(
        self,
        destination: str,
        *,
        probes_document: str | None = None,
    ) -> HostActionResult: ...


HostOperationsFactory = Callable[[HostControlExecutionContract], HostOperations]


def _mac_ssh_operations(
    contract: HostControlExecutionContract,
) -> HostOperations:
    from yoke_harness.ssh_mac_host_operations import SshMacHostOperations

    return SshMacHostOperations.from_contract(contract)


HOST_OPERATIONS_BY_KIND: dict[str, HostOperationsFactory] = {
    MAC_SSH_HOST_KIND: _mac_ssh_operations,
}


def host_operations_for(
    contract: HostControlExecutionContract,
) -> HostOperations:
    """Return the implementation the contract's declared host kind names."""
    kind = validate_test_machine_host_kind(contract.settings.get("host_kind"))
    factory = HOST_OPERATIONS_BY_KIND.get(kind)
    if factory is None:
        raise TestMachineCapabilityError(
            f"host kind {kind!r} has no operations implementation on this "
            "machine; upgrade Yoke or register a machine of a supported kind"
        )
    return factory(contract)


__all__ = [
    "HOST_OPERATIONS_BY_KIND",
    "HostOperations",
    "HostOperationsFactory",
    "host_operations_for",
]
