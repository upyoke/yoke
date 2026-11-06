"""Runtime interface for ssh mac terminal capture."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class SshMacTerminalCapture(Protocol):
    """Operations and values supplied by the executing adapter."""

    RunRemote: Any
    capture_screen: Callable[..., Any]
    close_terminal_session: Callable[..., Any]
    close_terminal_window: Callable[..., Any]
    detect_terminal_backend: Callable[..., Any]
    open_terminal_window: Callable[..., Any]
    resize_terminal_session: Callable[..., Any]
    send_terminal_input: Callable[..., Any]
    wait_for_text: Callable[..., Any]


def get_ssh_mac_terminal_capture() -> SshMacTerminalCapture:
    return cast(SshMacTerminalCapture, load_port("ssh_mac_terminal_capture", SshMacTerminalCapture))
