"""Runtime interface for ssh windows host operations."""

from __future__ import annotations

from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class SshWindowsHostOperations(Protocol):
    """Operations and values supplied by the executing adapter."""

    SshWindowsHostOperations: type[Any]


def get_ssh_windows_host_operations() -> SshWindowsHostOperations:
    return cast(SshWindowsHostOperations, load_port("ssh_windows_host_operations", SshWindowsHostOperations))
