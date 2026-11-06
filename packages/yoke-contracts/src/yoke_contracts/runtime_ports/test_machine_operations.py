"""Runtime interface for test machine operations."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class TestMachineOperations(Protocol):
    """Operations and values supplied by the executing adapter."""

    LocalHostControlSubmission: type[Any]
    execute_host_operation_contract: Callable[..., Any]


def get_test_machine_operations() -> TestMachineOperations:
    return cast(TestMachineOperations, load_port("test_machine_operations", TestMachineOperations))
