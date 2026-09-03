"""Compatibility imports for direct Terminal.app host control."""

from yoke_harness.ssh_mac_display_frame import (
    DisplayFrame,
    DisplayFrameUnavailable,
    place_terminal_app_window,
    resolve_display_frame,
    window_layout,
)
from yoke_harness.ssh_mac_terminal_app import (
    KeystrokeDelivery,
    RunRemote,
    capture_terminal_app_transcript,
    close_terminal_app_window,
    open_terminal_app_window,
    run_osascript,
    send_terminal_app_keys,
)
from yoke_harness.ssh_mac_terminal_bridge_check import (
    verify_terminal_app_control,
)
from yoke_harness.ssh_mac_terminal_screenshot import (
    ScreenCapture,
    capture_terminal_app_screen,
)


__all__ = [
    "DisplayFrame",
    "DisplayFrameUnavailable",
    "KeystrokeDelivery",
    "RunRemote",
    "ScreenCapture",
    "capture_terminal_app_screen",
    "capture_terminal_app_transcript",
    "close_terminal_app_window",
    "open_terminal_app_window",
    "place_terminal_app_window",
    "resolve_display_frame",
    "run_osascript",
    "send_terminal_app_keys",
    "verify_terminal_app_control",
    "window_layout",
]
