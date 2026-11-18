"""The Linux desktop a browser approval runs on, and quitting its Chromium.

The approval itself runs in the operator identity's browser
(``identity_browser_approval``), which the installer opens through
``BROWSER``; this module only starts the test user's XFCE desktop session the
installer's terminal and that browser need, and quits Chromium before a
capture or reset so its cookie store is on disk.
"""

from __future__ import annotations

import json
from pathlib import Path
import shlex
from typing import Any

from yoke_contracts.machine_qa_failures import bounded_machine_qa_diagnostic
from yoke_harness import linux_platform_payload, linux_chromium_processes, linux_desktop_chromium
from yoke_harness.linux_desktop_session import ensure_desktop
from yoke_harness.ssh_mac_sign_in_apps import SIGN_IN_APP_QUIT_NOT_PROVED
from yoke_contracts.test_machine_types import HostActionResult

BROWSER = "Chromium"
NO_DESKTOP = "headless_linux_browser_approval_unavailable"
NO_DESKTOP_RECOVERY = (
    "Browser approval on Linux runs in the test user's XFCE desktop. "
    "Provision the desktop and store desktop_password as "
    ".yoke/docs/verification/test-machines/linux-host-provisioning.md describes, then rerun."
)
HELPER_UNREADABLE = "linux_desktop_chromium_unreadable"
_HOST_TIMEOUT_SECONDS = 90


def _quit_program() -> str:
    return "\n".join(
        [
            linux_platform_payload.source(),
            Path(linux_chromium_processes.__file__).read_text(encoding="utf-8"),
            Path(linux_desktop_chromium.__file__)
            .read_text(encoding="utf-8")
            .replace(
                "from yoke_harness import linux_chromium_processes as native_processes",
                "",
            )
            .replace("native_processes.", ""),
            "main()\n",
        ]
    )


def prepare_desktop(control: Any) -> HostActionResult:
    """Start the test user's desktop session before the installer runs."""
    try:
        receipt = ensure_desktop(control)
    except RuntimeError as exc:
        return HostActionResult(
            False, {"recovery": f"{exc} {NO_DESKTOP_RECOVERY}"}, NO_DESKTOP
        )
    return HostActionResult(
        True,
        {
            "environment": receipt["environment"],
            "desktop_session": receipt["desktop_session"],
        },
    )


def quit_desktop_chromium(control: Any) -> HostActionResult:
    """Quit Chromium so its cookie store is on disk before capture or reset."""
    argv = ["/usr/bin/python3", "-c", _quit_program(), "quit"]
    result = control._run(shlex.join(argv), timeout=_HOST_TIMEOUT_SECONDS)
    try:
        stopped = json.loads(result.stdout.strip().splitlines()[-1])
        if not isinstance(stopped, dict):
            raise ValueError
    except (ValueError, IndexError):
        stopped = {
            "ok": False,
            "reason": HELPER_UNREADABLE,
            "exit_code": result.returncode,
            "stderr": bounded_machine_qa_diagnostic(
                result.stderr, getattr(control, "secret_values", ())
            ),
            "recovery": "The Chromium quit helper exited "
            + str(result.returncode)
            + " without a receipt; restore SSH and python3 on the host, then rerun.",
        }
    if not stopped.get("ok"):
        # A helper that never ran names its own failure; one that ran refused to quit.
        reason = stopped.pop("reason", None)
        return HostActionResult(
            False,
            {"app": BROWSER, "reason": reason, **stopped},
            reason if reason == HELPER_UNREADABLE else SIGN_IN_APP_QUIT_NOT_PROVED,
        )
    return HostActionResult(
        True, {"sign_in_apps_quit": [BROWSER] if stopped.get("quit") else []}
    )


__all__ = ["NO_DESKTOP", "prepare_desktop", "quit_desktop_chromium"]
