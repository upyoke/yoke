"""Desktop PNG capture over the existing credential-owned SSH transport."""

from __future__ import annotations

import base64
import hashlib
import shlex
import time
from uuid import uuid4

from yoke_contracts.machine_screenshot import screenshot_png
from yoke_harness.test_machine_types import HostActionResult


def _remote_png(control, remote):
    read = control._run("base64 < " + shlex.quote(remote), timeout=30)
    if read.returncode:
        raise ValueError(
            "desktop_screenshot_read_failed: repair the test user's capture path and retry"
        )
    return screenshot_png("".join(read.stdout.split()))


def _linux_capture(control, remote):
    from yoke_harness.linux_desktop_session import desktop_command
    from yoke_harness.linux_desktop_state import (
        DESKTOP_POLL_INTERVAL_SECONDS,
        DESKTOP_READY_TIMEOUT_SECONDS,
    )

    captured = desktop_command(control, ["scrot", "--overwrite", remote], timeout=30)
    session = captured.desktop_session
    deadline = time.monotonic() + DESKTOP_READY_TIMEOUT_SECONDS
    while not captured.returncode:
        try:
            return captured, _remote_png(control, remote)
        except ValueError as exc:
            if (
                session != "started"
                or str(exc.__cause__) != "blank desktop"
                or time.monotonic() >= deadline
            ):
                raise
        # XFCE can exist before its first frame; reuse that same desktop.
        time.sleep(DESKTOP_POLL_INTERVAL_SECONDS)
        captured = desktop_command(
            control, ["scrot", "--overwrite", remote], timeout=30
        )
        captured.desktop_session = session
    return captured, None


def capture_desktop(control) -> HostActionResult:
    """Capture one test desktop and carry its bytes to the operation submitter."""
    remote = "/tmp/yoke-desktop-" + uuid4().hex + ".png"
    session_evidence = {}
    linux_png = None
    try:
        if control.os == "macos":
            from yoke_harness.ssh_mac_gui_session import run_terminal_app_command
            from yoke_harness.ssh_mac_host_session_state import (
                display_lock_recovery,
                probe_host_display_context,
            )
            from yoke_contracts.machine_qa_terminal_bridge import (
                terminal_bridge_recovery,
            )

            context = probe_host_display_context(
                control._run, expected_console_user=control._user
            )
            code = None
            if context["console_user"] != control._user:
                code = "terminal_console_user_mismatch"
            elif context["display_locked"] is not False:
                code = "terminal_display_locked"
            if code:
                recovery = (
                    display_lock_recovery(context)
                    if code == "terminal_display_locked"
                    else terminal_bridge_recovery(code)
                )
                return HostActionResult(False, {**context, "recovery": recovery}, code)

            captured = run_terminal_app_command(
                control._run,
                argv=["/usr/sbin/screencapture", "-x", "-D", "1", remote],
                timeout=30,
            )
        elif control.os in {"linux", "windows"}:
            captured, linux_png = _linux_capture(control, remote)
            session_evidence = {"desktop_session": captured.desktop_session}
        else:
            raise ValueError(
                "test_machine_os_unsupported: choose macos, linux or windows"
            )
        if captured.returncode:
            return HostActionResult(
                False,
                {
                    "exit_code": captured.returncode,
                    "diagnostic": captured.stderr[-1000:],
                    "recovery": "Unlock the dedicated test desktop and verify its capture tool and permissions; provision Linux XFCE with ops/machine-qa/provision_linux_desktop.py.",
                },
                "desktop_screenshot_failed",
            )
        content, (width, height) = linux_png or _remote_png(control, remote)
        return HostActionResult(
            True,
            {
                "os": control.os,
                **session_evidence,
                "sha256": hashlib.sha256(content).hexdigest(),
                "width": width,
                "height": height,
                "artifact_token": "desktop",
                "capture_artifact": {
                    "token": "desktop",
                    "filename": "desktop.png",
                    "content_type": "image/png",
                    "content_base64": base64.b64encode(content).decode("ascii"),
                },
            },
        )
    except (RuntimeError, ValueError) as exc:
        detail = str(exc)
        if detail.startswith("screenshot_png_invalid:") and exc.__cause__ is not None:
            detail += "; capture validation: " + str(exc.__cause__)
        return HostActionResult(False, {"recovery": detail}, str(exc).split(":", 1)[0])
    finally:
        control._run("rm -f " + shlex.quote(remote), timeout=10)
