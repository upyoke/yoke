"""Runtime interface for ssh mac host session state."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class SshMacHostSessionState(Protocol):
    """Operations and values supplied by the executing adapter."""

    read_load_average: Callable[..., Any]


def get_ssh_mac_host_session_state() -> SshMacHostSessionState:
    return cast(SshMacHostSessionState, load_port("ssh_mac_host_session_state", SshMacHostSessionState))
