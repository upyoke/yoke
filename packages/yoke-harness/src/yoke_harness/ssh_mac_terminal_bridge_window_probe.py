"""Open one Terminal window and prove focus, typing, transcript, and capture.

These are the capabilities that only exist once a window does, so they are
separated from the host-level control surfaces the diagnosis checks first: a
window probe that runs before the console session and privacy grants are
established measures nothing an operator can act on.
"""

from __future__ import annotations

import shlex
from uuid import uuid4

from yoke_contracts.machine_qa_terminal_bridge import (
    TERMINAL_BRIDGE_CHECKS,
    TERMINAL_DISPLAY_FRAME_UNAVAILABLE_ERROR_CODE,
    TERMINAL_KEYSTROKE_UNDELIVERED_ERROR_CODE,
    TERMINAL_TRANSCRIPT_TIMEOUT_ERROR_CODE,
    TERMINAL_WINDOW_FOCUS_TIMEOUT_ERROR_CODE,
)
from yoke_harness.ssh_mac_display_frame import (
    DisplayFrameUnavailable,
    RunRemote,
    resolve_display_frame,
    window_layout,
)
from yoke_harness.ssh_mac_terminal_app import (
    close_terminal_app_window,
    open_terminal_app_window,
    send_terminal_app_keys,
)
from yoke_harness.ssh_mac_terminal_bridge_check import (
    READY_BANNER,
    classify_capture_failure,
    driven_window_command,
    wait_for_transcript,
)
from yoke_harness.ssh_mac_terminal_bridge_report import BridgeDiagnosisReport
from yoke_harness.ssh_mac_terminal_screenshot import capture_terminal_app_region
from yoke_harness.ssh_mac_terminal_timing import (
    TRANSCRIPT_WAIT_BASE_SECONDS,
    load_scaled_wait,
)


DISPLAY_FRAME_CHECK = TERMINAL_BRIDGE_CHECKS[5]
WINDOW_LAUNCH_CHECK = TERMINAL_BRIDGE_CHECKS[6]
WINDOW_FOCUS_CHECK = TERMINAL_BRIDGE_CHECKS[7]
KEYSTROKE_CHECK = TERMINAL_BRIDGE_CHECKS[8]
TRANSCRIPT_CHECK = TERMINAL_BRIDGE_CHECKS[9]
SCREEN_CAPTURE_CHECK = TERMINAL_BRIDGE_CHECKS[10]


def probe_driven_window(report: BridgeDiagnosisReport, run: RunRemote) -> None:
    """Record every window-scoped capability, stopping at the first failure."""
    identity = uuid4().hex[:12]
    remote = f"/tmp/yoke-bridge-diagnose-{identity}.png"
    received = f"received-{identity}"
    load_average = report.host.get("load_average")
    transcript_wait = load_scaled_wait(TRANSCRIPT_WAIT_BASE_SECONDS, load_average)
    try:
        frame = resolve_display_frame(run)
    except DisplayFrameUnavailable as exc:
        report.record(
            DISPLAY_FRAME_CHECK,
            ok=False,
            observed={"error_detail": str(exc)},
            error_code=TERMINAL_DISPLAY_FRAME_UNAVAILABLE_ERROR_CODE,
        )
        return
    layout = window_layout(frame)
    report.record(
        DISPLAY_FRAME_CHECK,
        ok=True,
        observed={
            "display_visible_frame": list(frame.bounds()),
            "display_count": frame.display_count,
        },
    )
    window_id = open_terminal_app_window(
        run,
        command=driven_window_command(identity),
        bounds=layout.target,
    )
    try:
        if not report.record(
            WINDOW_LAUNCH_CHECK,
            ok=window_id is not None,
            observed={"window_id": window_id},
        ):
            return
        assert window_id is not None
        if not wait_for_transcript(
            run,
            window_id=window_id,
            expected=READY_BANNER,
            timeout_seconds=transcript_wait,
        ):
            report.record(
                WINDOW_FOCUS_CHECK,
                ok=False,
                observed={
                    "awaited": READY_BANNER,
                    "wait_seconds": transcript_wait,
                    "load_average": load_average,
                },
                error_code=TERMINAL_TRANSCRIPT_TIMEOUT_ERROR_CODE,
            )
            return
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
        if not report.record(
            WINDOW_FOCUS_CHECK,
            ok=delivery.focused,
            observed={
                "frontmost_process": delivery.frontmost_process,
                "wait_seconds": delivery.focus_wait_seconds,
                "load_average": load_average,
            },
            error_code=TERMINAL_WINDOW_FOCUS_TIMEOUT_ERROR_CODE,
        ):
            return
        if not report.record(
            KEYSTROKE_CHECK,
            ok=delivery.delivered,
            observed={"keys_sent": len((identity, "Enter"))},
            error_code=TERMINAL_KEYSTROKE_UNDELIVERED_ERROR_CODE,
        ):
            return
        if not report.record(
            TRANSCRIPT_CHECK,
            ok=wait_for_transcript(
                run,
                window_id=window_id,
                expected=received,
                timeout_seconds=transcript_wait,
            ),
            observed={
                "wait_seconds": transcript_wait,
                "load_average": load_average,
            },
            error_code=TERMINAL_TRANSCRIPT_TIMEOUT_ERROR_CODE,
        ):
            return
        after = capture_terminal_app_region(
            run,
            remote=remote,
            window_id=window_id,
            frame=frame,
            layout=layout,
        )
        if (
            before.payload is not None
            and after.payload is not None
            and after.payload != before.payload
        ):
            report.record(
                SCREEN_CAPTURE_CHECK,
                ok=True,
                observed={"frames_differed": True},
            )
            return
        error_code, context = classify_capture_failure(
            run,
            before=before,
            after=after,
            expected_console_user=report.expected_console_user,
        )
        report.record(
            SCREEN_CAPTURE_CHECK,
            ok=False,
            observed={
                **after.diagnostics,
                **context,
                "frames_differed": False,
                "before_capture_error": before.error_code,
                "after_capture_error": after.error_code,
            },
            error_code=error_code,
        )
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


__all__ = ["probe_driven_window"]
