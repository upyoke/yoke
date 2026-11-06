"""Runtime interface for ssh mac terminal automation probe."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class SshMacTerminalAutomationProbe(Protocol):
    """Operations and values supplied by the executing adapter."""

    terminal_system_events_automation: Callable[..., Any]


def get_ssh_mac_terminal_automation_probe() -> SshMacTerminalAutomationProbe:
    return cast(SshMacTerminalAutomationProbe, load_port("ssh_mac_terminal_automation_probe", SshMacTerminalAutomationProbe))
