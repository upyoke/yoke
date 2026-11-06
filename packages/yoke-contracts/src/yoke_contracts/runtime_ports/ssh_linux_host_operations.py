"""Runtime interface for ssh linux host operations."""

from __future__ import annotations

from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class SshLinuxHostOperations(Protocol):
    """Operations and values supplied by the executing adapter."""

    SshLinuxHostOperations: type[Any]


def get_ssh_linux_host_operations() -> SshLinuxHostOperations:
    return cast(SshLinuxHostOperations, load_port("ssh_linux_host_operations", SshLinuxHostOperations))
