"""Desktop PNG capture over the existing credential-owned SSH transport."""

from __future__ import annotations

import base64
import hashlib
import shlex
from uuid import uuid4

from yoke_contracts.machine_screenshot import screenshot_png
from yoke_harness.test_machine_types import HostActionResult


def capture_desktop(control) -> HostActionResult:
    """Capture one test desktop and carry its bytes to the operation submitter."""
    remote = "/tmp/yoke-desktop-" + uuid4().hex + ".png"
    session_evidence = {}
    try:
        if control.os == "windows":
            from yoke_harness.windows_desktop_screenshot import windows_desktop_png

            encoded, session_id = windows_desktop_png(control)
            session_evidence = {"windows_session_id": session_id}
        elif control.os == "macos":
            from yoke_harness.ssh_mac_gui_session import run_terminal_app_command
            from yoke_harness.ssh_mac_host_session_state import (
                probe_host_display_context,
            )
            from yoke_contracts.machine_qa_terminal_bridge import (
                terminal_bridge_recovery,
            )

            context = probe_host_display_context(control._run)
            code = None
            if context["console_user"] != control._user:
                code = "terminal_console_user_mismatch"
            elif context["display_locked"] is not False:
                code = "terminal_display_locked"
            if code:
                return HostActionResult(
                    False, {**context, "recovery": terminal_bridge_recovery(code)}, code
                )

            captured = run_terminal_app_command(
                control._run,
                argv=["/usr/sbin/screencapture", "-x", "-D", "1", remote],
                timeout=30,
            )
        elif control.os == "linux":
            from yoke_harness.linux_desktop_session import desktop_command

            captured = desktop_command(
                control, ["scrot", "--overwrite", remote], timeout=30
            )
        else:
            raise ValueError(
                "test_machine_os_unsupported: choose macos, linux or windows"
            )
        if control.os != "windows" and captured.returncode:
            return HostActionResult(
                False,
                {
                    "exit_code": captured.returncode,
                    "diagnostic": captured.stderr[-1000:],
                    "recovery": "Unlock the dedicated test desktop and verify its capture tool and permissions; provision Linux XFCE with ops/machine-qa/provision_linux_desktop.py.",
                },
                "desktop_screenshot_failed",
            )
        if control.os != "windows":
            read = control._run("base64 < " + shlex.quote(remote), timeout=30)
            if read.returncode:
                raise ValueError(
                    "desktop_screenshot_read_failed: repair the test user's capture path and retry"
                )
            encoded = "".join(read.stdout.split())
        content, (width, height) = screenshot_png(encoded)
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
        return HostActionResult(
            False, {"recovery": str(exc)}, str(exc).split(":", 1)[0]
        )
    finally:
        if control.os != "windows":
            control._run("rm -f " + shlex.quote(remote), timeout=10)
