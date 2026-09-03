"""Prove direct Terminal.app launch, focus, input, transcript, and capture."""

from __future__ import annotations

import shlex
import time
from typing import Any
from uuid import uuid4

from yoke_contracts.machine_qa_terminal_bridge import (
    TERMINAL_APP_CONTROL_UNAVAILABLE_ERROR_CODE,
    TERMINAL_BRIDGE_RECOVERY,
    TERMINAL_CONSOLE_USER_MISMATCH_ERROR_CODE,
    TERMINAL_DISPLAY_FRAME_UNAVAILABLE_ERROR_CODE,
    TERMINAL_DISPLAY_LOCKED_ERROR_CODE,
    TERMINAL_KEYSTROKE_UNDELIVERED_ERROR_CODE,
    TERMINAL_SCREEN_RECORDING_REQUIRED_ERROR_CODE,
    TERMINAL_TRANSCRIPT_TIMEOUT_ERROR_CODE,
    TERMINAL_WINDOW_FOCUS_TIMEOUT_ERROR_CODE,
)
from yoke_harness.ssh_mac_display_frame import (
    DisplayFrameUnavailable,
    RunRemote,
    resolve_display_frame,
    window_layout,
)
from yoke_harness.ssh_mac_host_session_state import (
    probe_host_display_context,
    read_load_average,
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
)
from yoke_harness.ssh_mac_terminal_timing import (
    BRIDGE_POLL_SECONDS,
    TRANSCRIPT_WAIT_BASE_SECONDS,
    load_scaled_wait,
)


READY_BANNER = "terminal-app-ready"


def named_failure(
    error_code: str,
    diagnostics: dict[str, Any],
) -> dict[str, Any]:
    """Attach the condition's name and its recovery to what was observed."""
    return {
        **diagnostics,
        "error_reason": error_code,
        "recovery": TERMINAL_BRIDGE_RECOVERY[error_code],
    }


def classify_capture_failure(
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


def wait_for_transcript(
    run: RunRemote,
    *,
    window_id: int,
    expected: str,
    timeout_seconds: float,
) -> bool:
    """Wait for *expected* to appear in one window's visible contents."""
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    while True:
        if expected in capture_terminal_app_transcript(run, window_id=window_id):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(BRIDGE_POLL_SECONDS)


def driven_window_command(identity: str) -> str:
    """Return the shell one-liner the driven window runs while under test."""
    return (
        f"printf '{READY_BANNER}\\n'; "
        "IFS= read -r value; printf 'received-%s\\n' \"$value\"; sleep 15"
    )


def verify_terminal_app_control(
    run: RunRemote,
    *,
    expected_console_user: str | None = None,
) -> tuple[bool, dict[str, Any], str | None]:
    """Exercise direct launch, focus, native input, transcript, and capture.

    This is verification's single pass/fail read of the bridge. When it fails,
    `yoke test-machine bridge diagnose` runs each capability on its own and
    names the host condition -- which is why every failure here carries a
    named reason rather than one umbrella code.
    """
    identity = uuid4().hex[:12]
    session = f"yoke-terminal-app-{identity}"
    remote = f"/tmp/{session}.png"
    received = f"received-{identity}"
    load_average = read_load_average(run)
    transcript_wait = load_scaled_wait(TRANSCRIPT_WAIT_BASE_SECONDS, load_average)
    checks: dict[str, Any] = {
        "terminal_app_launch": False,
        "terminal_app_focus": False,
        "terminal_app_input": False,
        "terminal_app_transcript": False,
        "terminal_app_screenshot": False,
        "host_load_average": load_average,
        "transcript_wait_seconds": transcript_wait,
    }
    try:
        frame = resolve_display_frame(run)
    except DisplayFrameUnavailable as exc:
        checks["capture_diagnostics"] = named_failure(
            TERMINAL_DISPLAY_FRAME_UNAVAILABLE_ERROR_CODE,
            {"error_detail": str(exc)},
        )
        return False, checks, TERMINAL_DISPLAY_FRAME_UNAVAILABLE_ERROR_CODE
    layout = window_layout(frame)
    window_id = open_terminal_app_window(
        run,
        command=driven_window_command(identity),
        bounds=layout.target,
    )
    try:
        if window_id is None:
            return False, checks, TERMINAL_APP_CONTROL_UNAVAILABLE_ERROR_CODE
        checks["terminal_app_launch"] = True
        if not wait_for_transcript(
            run,
            window_id=window_id,
            expected=READY_BANNER,
            timeout_seconds=transcript_wait,
        ):
            checks["capture_diagnostics"] = named_failure(
                TERMINAL_TRANSCRIPT_TIMEOUT_ERROR_CODE,
                {"awaited": READY_BANNER, "host_load_average": load_average},
            )
            return False, checks, TERMINAL_TRANSCRIPT_TIMEOUT_ERROR_CODE
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
        delivery = send_terminal_app_keys(
            run,
            window_id=window_id,
            keys=(identity, "Enter"),
            load_average=load_average,
        )
        checks["terminal_app_focus"] = delivery.focused
        checks["terminal_app_input"] = delivery.delivered
        checks["focus_wait_seconds"] = delivery.focus_wait_seconds
        if not delivery.focused:
            checks["capture_diagnostics"] = named_failure(
                TERMINAL_WINDOW_FOCUS_TIMEOUT_ERROR_CODE,
                {
                    "frontmost_process": delivery.frontmost_process,
                    "host_load_average": load_average,
                },
            )
            return False, checks, TERMINAL_WINDOW_FOCUS_TIMEOUT_ERROR_CODE
        if not delivery.delivered:
            checks["capture_diagnostics"] = named_failure(
                TERMINAL_KEYSTROKE_UNDELIVERED_ERROR_CODE,
                {"host_load_average": load_average},
            )
            return False, checks, TERMINAL_KEYSTROKE_UNDELIVERED_ERROR_CODE
        checks["terminal_app_transcript"] = wait_for_transcript(
            run,
            window_id=window_id,
            expected=received,
            timeout_seconds=transcript_wait,
        )
        if not checks["terminal_app_transcript"]:
            checks["capture_diagnostics"] = named_failure(
                TERMINAL_TRANSCRIPT_TIMEOUT_ERROR_CODE,
                {"awaited": received, "host_load_average": load_average},
            )
            return False, checks, TERMINAL_TRANSCRIPT_TIMEOUT_ERROR_CODE
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
            error_code, context = classify_capture_failure(
                run,
                before=before,
                after=after,
                expected_console_user=expected_console_user,
            )
            checks["capture_diagnostics"] = named_failure(
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
        return True, checks, None
    finally:
        run(f"rm -f {shlex.quote(remote)}", timeout=10)
        if window_id is not None:
            send_terminal_app_keys(
                run,
                window_id=window_id,
                keys=("C-c",),
                load_average=load_average,
            )
        close_terminal_app_window(run, window_id=window_id)


__all__ = [
    "READY_BANNER",
    "classify_capture_failure",
    "driven_window_command",
    "named_failure",
    "verify_terminal_app_control",
    "wait_for_transcript",
]
