"""Runtime interface for linux desktop state."""

from __future__ import annotations

from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class LinuxDesktopState(Protocol):
    """Operations and values supplied by the executing adapter."""

    RDP_PORT: Any


def get_linux_desktop_state() -> LinuxDesktopState:
    return cast(LinuxDesktopState, load_port("linux_desktop_state", LinuxDesktopState))
