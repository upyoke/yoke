"""Capture a driven Terminal.app window's region and name what blocked it."""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from pathlib import Path
import shlex
from typing import Any

from yoke_contracts.machine_qa_execution import (
    TERMINAL_SCREEN_CAPTURE_FAILED_ERROR_CODE,
    TERMINAL_WINDOW_OFF_SCREEN_ERROR_CODE,
)
from yoke_harness.ssh_mac_display_frame import (
    DisplayFrame,
    RunRemote,
    WindowLayout,
    window_layout,
)
from yoke_harness.ssh_mac_gui_session import run_terminal_app_command
from yoke_harness.ssh_mac_terminal_app import place_terminal_app_window


_CAPTURE_TOOL = "/usr/sbin/screencapture"
_CAPTURE_TIMEOUT_SECONDS = 20
_CAPTURE_SETTLE_SECONDS = "0.5"
_STDERR_EVIDENCE_LIMIT = 500


@dataclass(frozen=True)
class RegionCapture:
    """One region capture attempt plus everything it observed while trying."""

    payload: str | None
    diagnostics: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None


@dataclass(frozen=True)
class ScreenCapture:
    """A retained screenshot, or the named reason there is none."""

    path: Path | None
    error_code: str | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)


def probe_host_display_context(run: RunRemote) -> dict[str, Any]:
    """Read the host facts that decide whether any capture could have worked."""
    console = run("/usr/bin/stat -f%Su /dev/console", timeout=10)
    locked = run(
        "/usr/sbin/ioreg -n Root -d1 -k CGSSessionScreenIsLocked",
        timeout=10,
    )
    return {
        "console_user": (console.stdout.strip() if console.returncode == 0 else None),
        "display_locked": (
            '"CGSSessionScreenIsLocked" = Yes' in locked.stdout
            if locked.returncode == 0
            else None
        ),
    }


def capture_terminal_app_region(
    run: RunRemote,
    *,
    remote: str,
    window_id: int,
    frame: DisplayFrame,
    layout: WindowLayout,
) -> RegionCapture:
    """Place the window on-screen, then capture exactly its region.

    Placement comes first because a region capture of a window the display
    does not contain returns a valid, useless PNG while launch, input, and
    transcript all keep working — the signature that sent an operator to the
    console.
    """
    placed = place_terminal_app_window(
        run,
        window_id=window_id,
        frame=frame,
        bounds=layout.target,
    )
    diagnostics: dict[str, Any] = {
        "window_id": window_id,
        "window_bounds": list(placed) if placed else None,
        "helper_window_bounds": list(layout.helper),
        "display_visible_frame": list(frame.bounds()),
        "display_size": [frame.display_width, frame.display_height],
    }
    if placed is None or not frame.contains(placed):
        return RegionCapture(
            None,
            diagnostics,
            TERMINAL_WINDOW_OFF_SCREEN_ERROR_CODE,
        )
    left, top, right, bottom = placed
    capture_argv = [
        _CAPTURE_TOOL,
        "-x",
        "-R",
        f"{left},{top},{right - left},{bottom - top}",
        "-o",
        remote,
    ]
    diagnostics["command"] = shlex.join(capture_argv)
    # The capture runs inside Terminal.app so macOS applies Terminal's Screen
    # Recording grant, and through the command runner so its exit code and
    # stderr survive as evidence. The helper window is laid out clear of the
    # captured rectangle, and the settle delay lets the window server finish
    # compositing that placement.
    result = run_terminal_app_command(
        run,
        argv=[
            "/bin/sh",
            "-c",
            f"/bin/sleep {_CAPTURE_SETTLE_SECONDS}; exec " + shlex.join(capture_argv),
        ],
        timeout=_CAPTURE_TIMEOUT_SECONDS,
        display_frame=frame,
        bounds=layout.helper,
    )
    diagnostics["exit_code"] = result.returncode
    diagnostics["stderr"] = (result.stderr or "").strip()[:_STDERR_EVIDENCE_LIMIT]
    if result.returncode:
        return RegionCapture(
            None,
            diagnostics,
            TERMINAL_SCREEN_CAPTURE_FAILED_ERROR_CODE,
        )
    encoded = run(
        f"/bin/test -s {shlex.quote(remote)} && "
        f"/usr/bin/base64 < {shlex.quote(remote)}",
        timeout=10,
    )
    if encoded.returncode or not encoded.stdout.strip():
        diagnostics["capture_file_empty"] = True
        return RegionCapture(
            None,
            diagnostics,
            TERMINAL_SCREEN_CAPTURE_FAILED_ERROR_CODE,
        )
    return RegionCapture(encoded.stdout, diagnostics, None)


def capture_terminal_app_screen(
    run: RunRemote,
    *,
    session: str,
    key: str,
    evidence_root: Path,
    window_id: int,
    display_frame: DisplayFrame,
) -> ScreenCapture:
    """Retain one screenshot of the exact user-visible Terminal.app region."""
    remote = f"/tmp/{session}-{key}.png"
    try:
        capture = capture_terminal_app_region(
            run,
            remote=remote,
            window_id=window_id,
            frame=display_frame,
            layout=window_layout(display_frame),
        )
        if capture.payload is None:
            return ScreenCapture(None, capture.error_code, capture.diagnostics)
        try:
            payload = base64.b64decode(capture.payload)
        except ValueError:
            return ScreenCapture(
                None,
                TERMINAL_SCREEN_CAPTURE_FAILED_ERROR_CODE,
                {**capture.diagnostics, "capture_file_unreadable": True},
            )
    finally:
        run(f"rm -f {shlex.quote(remote)}", timeout=10)
    path = evidence_root / f"{key}.png"
    path.write_bytes(payload)
    return ScreenCapture(path, None, capture.diagnostics)


__all__ = [
    "RegionCapture",
    "ScreenCapture",
    "capture_terminal_app_region",
    "capture_terminal_app_screen",
    "probe_host_display_context",
]
