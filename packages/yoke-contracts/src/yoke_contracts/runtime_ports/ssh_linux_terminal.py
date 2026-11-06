"""Runtime interface for ssh linux terminal."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class SshLinuxTerminal(Protocol):
    """Operations and values supplied by the executing adapter."""

    LinuxTerminal: type[Any]
    LinuxTerminalWindowError: type[Any]
    run_linux_terminal_case: Callable[..., Any]


def get_ssh_linux_terminal() -> SshLinuxTerminal:
    return cast(SshLinuxTerminal, load_port("ssh_linux_terminal", SshLinuxTerminal))
