"""Runtime interface for ssh mac transport."""

from __future__ import annotations

from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class SshMacTransport(Protocol):
    """Operations and values supplied by the executing adapter."""

    SSH_OPTIONS: Any
    SshMacTransport: type[Any]


def get_ssh_mac_transport() -> SshMacTransport:
    return cast(SshMacTransport, load_port("ssh_mac_transport", SshMacTransport))
