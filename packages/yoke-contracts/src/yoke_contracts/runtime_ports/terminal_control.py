"""Runtime interface for terminal control."""

from __future__ import annotations

from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class TerminalControl(Protocol):
    """Operations and values supplied by the executing adapter."""

    DisplayFrameUnavailable: Any
    RunRemote: Any
    capture_terminal_app_screen: Any
    capture_terminal_app_transcript: Any
    close_terminal_app_window: Any
    open_terminal_app_window: Any
    resolve_display_frame: Any
    send_terminal_app_keys: Any
    window_layout: Any


def get_terminal_control() -> TerminalControl:
    return cast(TerminalControl, load_port("terminal_control", TerminalControl))
