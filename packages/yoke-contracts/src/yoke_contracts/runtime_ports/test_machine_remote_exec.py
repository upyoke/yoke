"""Runtime interface for test machine remote exec."""

from __future__ import annotations

from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class TestMachineRemoteExec(Protocol):
    """Operations and values supplied by the executing adapter."""

    host_key_options: Any


def get_test_machine_remote_exec() -> TestMachineRemoteExec:
    return cast(TestMachineRemoteExec, load_port("test_machine_remote_exec", TestMachineRemoteExec))
