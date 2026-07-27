"""Compatibility imports for client-side SSH terminal capture."""

from yoke_harness.ssh_mac_terminal_capture import (
    RunRemote,
    TerminalBackend,
    capture_screen,
    close_terminal_session,
    detect_terminal_backend,
    resize_terminal_session,
    send_terminal_input,
    verify_terminal_bridge,
    wait_for_text,
)


__all__ = [
    "RunRemote",
    "TerminalBackend",
    "capture_screen",
    "close_terminal_session",
    "detect_terminal_backend",
    "resize_terminal_session",
    "send_terminal_input",
    "verify_terminal_bridge",
    "wait_for_text",
]
