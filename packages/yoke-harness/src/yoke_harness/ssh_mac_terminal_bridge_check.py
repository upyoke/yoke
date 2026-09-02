"""Prove direct Terminal.app launch, input, transcript, and region capture."""

from __future__ import annotations

import shlex
import time
from typing import Any
from uuid import uuid4

from yoke_contracts.machine_qa_execution import (
    TERMINAL_CAPTURE_RECOVERY,
    TERMINAL_CONSOLE_USER_MISMATCH_ERROR_CODE,
    TERMINAL_DISPLAY_FRAME_UNAVAILABLE_ERROR_CODE,
    TERMINAL_DISPLAY_LOCKED_ERROR_CODE,
    TERMINAL_SCREEN_RECORDING_REQUIRED_ERROR_CODE,
)
from yoke_harness.ssh_mac_display_frame import (
    DisplayFrameUnavailable,
    RunRemote,
    resolve_display_frame,
    window_layout,
)
from yoke_harness.ssh_mac_terminal_app import (
    capture_terminal_app_transcript,
    close_terminal_app_window,
    open_terminal_app_window,
    send_terminal_app_keys,
)
from yoke_harness.ssh_mac_terminal_screenshot import (
    RegionCapture,
    capture_terminal_app_region,
    probe_host_display_context,
)


TERMINAL_APP_CONTROL_UNAVAILABLE_ERROR_CODE = "terminal_app_control_unavailable"
_READY_TIMEOUT_SECONDS = 5
_READY_POLL_SECONDS = 0.1


def _named_failure(
    error_code: str,
    diagnostics: dict[str, Any],
) -> dict[str, Any]:
    return {
        **diagnostics,
        "error_reason": error_code,
        "recovery": TERMINAL_CAPTURE_RECOVERY[error_code],
    }


def _classify_capture_failure(
    run: RunRemote,
    *,
    before: RegionCapture,
    after: RegionCapture,
    expected_console_user: str | None,
) -> tuple[str, dict[str, Any]]:
    """Name the condition an operator has to change, host session first."""
    context = probe_host_display_context(run)
    console_user = context["console_user"]
    if console_user and expected_console_user and console_user != expected_console_user:
        return TERMINAL_CONSOLE_USER_MISMATCH_ERROR_CODE, context
    if context["display_locked"]:
        return TERMINAL_DISPLAY_LOCKED_ERROR_CODE, context
    for capture in (before, after):
        if capture.error_code:
            return capture.error_code, context
    # Both captures succeeded yet hold the same bytes across a display change
    # the transcript already proved: Terminal.app is capturing wallpaper.
    return TERMINAL_SCREEN_RECORDING_REQUIRED_ERROR_CODE, context


def _wait_for_transcript(run: RunRemote, window_id: int, expected: str) -> bool:
    deadline = time.monotonic() + _READY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if expected in capture_terminal_app_transcript(run, window_id=window_id):
            return True
        time.sleep(_READY_POLL_SECONDS)
    return False


def verify_terminal_app_control(
    run: RunRemote,
    *,
    expected_console_user: str | None = None,
) -> tuple[bool, dict[str, Any], str | None]:
    """Exercise direct launch, native input, transcript, and region capture."""
    identity = uuid4().hex[:12]
    session = f"yoke-terminal-app-{identity}"
    remote = f"/tmp/{session}.png"
    received = f"received-{identity}"
    command = (
        "printf 'terminal-app-ready\\n'; "
        "IFS= read -r value; printf 'received-%s\\n' \"$value\"; sleep 15"
    )
    checks: dict[str, Any] = {
        "terminal_app_launch": False,
        "terminal_app_input": False,
        "terminal_app_transcript": False,
        "terminal_app_screenshot": False,
    }
    try:
        frame = resolve_display_frame(run)
    except DisplayFrameUnavailable as exc:
        checks["capture_diagnostics"] = _named_failure(
            TERMINAL_DISPLAY_FRAME_UNAVAILABLE_ERROR_CODE,
            {"error_detail": str(exc)},
        )
        return False, checks, TERMINAL_DISPLAY_FRAME_UNAVAILABLE_ERROR_CODE
    layout = window_layout(frame)
    window_id = open_terminal_app_window(
        run,
        command=command,
        display_frame=frame,
        bounds=layout.target,
    )
    try:
        if window_id is None:
            return False, checks, TERMINAL_APP_CONTROL_UNAVAILABLE_ERROR_CODE
        checks["terminal_app_launch"] = True
        if not _wait_for_transcript(run, window_id, "terminal-app-ready"):
            return False, checks, TERMINAL_APP_CONTROL_UNAVAILABLE_ERROR_CODE
        # Frame before the window's content changes: only the ready banner
        # and prompt are on screen.
        before = capture_terminal_app_region(
            run,
            remote=remote,
            window_id=window_id,
            frame=frame,
            layout=layout,
        )
        run(f"rm -f {shlex.quote(remote)}", timeout=10)
        checks["terminal_app_input"] = send_terminal_app_keys(
            run,
            window_id=window_id,
            keys=(identity, "Enter"),
        )
        checks["terminal_app_transcript"] = _wait_for_transcript(
            run,
            window_id,
            received,
        )
        if not checks["terminal_app_transcript"]:
            return False, checks, TERMINAL_APP_CONTROL_UNAVAILABLE_ERROR_CODE
        # The transcript proved the visible content changed; a capture that
        # still matches the earlier frame is not seeing this window.
        after = capture_terminal_app_region(
            run,
            remote=remote,
            window_id=window_id,
            frame=frame,
            layout=layout,
        )
        checks["terminal_app_screenshot"] = (
            before.payload is not None
            and after.payload is not None
            and after.payload != before.payload
        )
        if not checks["terminal_app_screenshot"]:
            error_code, context = _classify_capture_failure(
                run,
                before=before,
                after=after,
                expected_console_user=expected_console_user,
            )
            checks["capture_diagnostics"] = _named_failure(
                error_code,
                {
                    **after.diagnostics,
                    **context,
                    "frames_differed": False,
                    "before_capture_error": before.error_code,
                    "after_capture_error": after.error_code,
                },
            )
            return False, checks, error_code
        ok = all(bool(value) for value in checks.values())
        return ok, checks, None if ok else TERMINAL_APP_CONTROL_UNAVAILABLE_ERROR_CODE
    finally:
        run(f"rm -f {shlex.quote(remote)}", timeout=10)
        if window_id is not None:
            send_terminal_app_keys(
                run,
                window_id=window_id,
                keys=("C-c",),
            )
        close_terminal_app_window(run, window_id=window_id)


__all__ = [
    "TERMINAL_APP_CONTROL_UNAVAILABLE_ERROR_CODE",
    "verify_terminal_app_control",
]
