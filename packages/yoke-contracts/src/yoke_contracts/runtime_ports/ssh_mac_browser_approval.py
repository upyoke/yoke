"""Runtime interface for ssh mac browser approval."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class SshMacBrowserApproval(Protocol):
    """Operations and values supplied by the executing adapter."""

    approve_machine_in_safari: Callable[..., Any]


def get_ssh_mac_browser_approval() -> SshMacBrowserApproval:
    return cast(SshMacBrowserApproval, load_port("ssh_mac_browser_approval", SshMacBrowserApproval))
