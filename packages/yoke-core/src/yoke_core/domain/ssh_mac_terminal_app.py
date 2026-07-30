"""Compatibility imports for direct Terminal.app host control."""

from yoke_harness.ssh_mac_terminal_app import (
    RunRemote,
    TERMINAL_WINDOW_BOUNDS,
    capture_terminal_app_screen,
    capture_terminal_app_transcript,
    close_terminal_app_window,
    open_terminal_app_window,
    send_terminal_app_keys,
    verify_terminal_app_control,
)


__all__ = [
    "RunRemote",
    "TERMINAL_WINDOW_BOUNDS",
    "capture_terminal_app_screen",
    "capture_terminal_app_transcript",
    "close_terminal_app_window",
    "open_terminal_app_window",
    "send_terminal_app_keys",
    "verify_terminal_app_control",
]
