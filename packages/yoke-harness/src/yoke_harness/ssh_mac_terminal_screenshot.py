"""Capture a driven Terminal.app window's region and name what blocked it."""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from pathlib import Path
import shlex
from typing import Any

from yoke_contracts.machine_qa_terminal_bridge import (
    TERMINAL_SCREEN_CAPTURE_FAILED_ERROR_CODE,
    TERMINAL_WINDOW_OFF_SCREEN_ERROR_CODE,
)
from yoke_harness.ssh_mac_capture_clearance import Clearance, clear_capture_window
from yoke_harness.ssh_mac_display_frame import (
    DisplayFrame,
    RunRemote,
    WindowLayout,
    place_terminal_app_window,
    window_layout,
)
from yoke_harness.ssh_mac_gui_session import run_terminal_app_command


_CAPTURE_TOOL = "/usr/sbin/screencapture"
_CROP_TOOL = "/usr/bin/sips"
_CAPTURE_TIMEOUT_SECONDS = 20
_CAPTURE_SETTLE_SECONDS = "0.5"
# How long the capture command waits for the caller to finish clearing its
# window before it gives up: 300 polls of 0.1s.
_GATE_POLLS = 300
CAPTURE_GATE_NOT_RELEASED = "capture_gate_not_released"
_STDERR_EVIDENCE_LIMIT = 500


@dataclass(frozen=True)
class RegionCapture:
    """One region capture attempt plus everything it observed while trying."""

    payload: str | None
    diagnostics: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None
    degraded_detail: str | None = None


@dataclass(frozen=True)
class ScreenCapture:
    """A retained screenshot, or the named reason there is none.

    `degraded_detail` names why a retained image cannot be trusted, with the
    window bounds observed and the recovery.
    """

    path: Path | None
    error_code: str | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)
    degraded_detail: str | None = None


def capture_terminal_app_region(
    run: RunRemote,
    *,
    remote: str,
    window_id: int,
    frame: DisplayFrame,
    layout: WindowLayout,
) -> RegionCapture:
    """Place the window on-screen, then capture exactly its region.

    Placement comes first because a capture of a window the display does not
    contain returns a valid, useless PNG while launch, input, and transcript
    all keep working — the signature that sent an operator to the console.

    Placement covers position and minimized state but not Spaces, because
    every window this path captures was opened by the same run and so is on
    the Space that was current: a capture of a window this code did not create
    would need to establish that too.
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
        "display_count": frame.display_count,
        "capture_origin": list(frame.capture_origin),
        "backing_scale": frame.backing_scale,
    }
    if placed is None or not frame.contains(placed):
        return RegionCapture(
            None,
            diagnostics,
            TERMINAL_WINDOW_OFF_SCREEN_ERROR_CODE,
        )
    left, top, right, bottom = frame.capture_rectangle(placed)
    diagnostics["capture_rectangle"] = [left, top, right, bottom]
    scale = frame.backing_scale
    whole_display = remote + ".display.png"
    # The whole display is captured and then cropped to the window, rather
    # than captured by region: on at least one supported Mac the region form
    # answers "could not create image from display with rect" for every
    # rectangle that intersects the display, down to 100x100, while the
    # whole-display form succeeds on that same host in the same second.
    # Cropping afterwards keeps the artifact exactly the window, and the crop
    # is expressed in the captured image's own pixels -- the placed rectangle
    # converted to the display's corner, times its backing scale factor.
    capture_argv = [_CAPTURE_TOOL, "-x", "-D", "1", "-o", whole_display]
    crop_argv = [
        _CROP_TOOL,
        "-c",
        str(round((bottom - top) * scale)),
        str(round((right - left) * scale)),
        "--cropOffset",
        str(round(top * scale)),
        str(round(left * scale)),
        whole_display,
        "--out",
        remote,
    ]
    diagnostics["command"] = shlex.join(capture_argv) + " && " + shlex.join(crop_argv)
    gate = remote + ".gate"
    clearance: list[Clearance] = []

    def clear_then_release(capture_window_id: int) -> None:
        try:
            clearance.append(
                clear_capture_window(
                    run,
                    capture_window_id=capture_window_id,
                    app_window_id=window_id,
                    frame=frame,
                )
            )
        finally:
            run(f"/usr/bin/touch {shlex.quote(gate)}", timeout=10)

    # The capture runs inside Terminal.app so macOS applies Terminal's Screen
    # Recording grant, and through the command runner so its exit code and
    # stderr survive as evidence. Its window opens at the helper bounds, and
    # the command then holds at the gate until both windows' bounds have been
    # read back and the helper cleared off the captured window; the settle
    # delay lets the window server finish compositing that placement.
    held = (
        f"i=0; while [ ! -e {shlex.quote(gate)} ]; do i=$((i+1)); "
        f"if [ $i -gt {_GATE_POLLS} ]; then "
        f"echo {CAPTURE_GATE_NOT_RELEASED} >&2; exit 1; fi; /bin/sleep 0.1; done; "
    )
    try:
        result = run_terminal_app_command(
            run,
            argv=[
                "/bin/sh",
                "-c",
                held
                + f"/bin/sleep {_CAPTURE_SETTLE_SECONDS}; "
                + shlex.join(capture_argv)
                + " && "
                + shlex.join(crop_argv)
                + " >/dev/null",
            ],
            timeout=_CAPTURE_TIMEOUT_SECONDS + _GATE_POLLS // 10,
            bounds=layout.helper,
            on_window_open=clear_then_release,
        )
    finally:
        run(f"rm -f {shlex.quote(whole_display)} {shlex.quote(gate)}", timeout=10)
    degraded = clearance[0] if clearance else None
    if degraded is not None:
        diagnostics["capture_window_clearance"] = {
            "degraded_reason": degraded.degraded_reason,
            **degraded.evidence,
        }
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
    return RegionCapture(
        encoded.stdout,
        diagnostics,
        None,
        degraded.detail if degraded is not None else None,
    )


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
    return ScreenCapture(path, None, capture.diagnostics, capture.degraded_detail)


__all__ = [
    "CAPTURE_GATE_NOT_RELEASED",
    "RegionCapture",
    "ScreenCapture",
    "capture_terminal_app_region",
    "capture_terminal_app_screen",
]
