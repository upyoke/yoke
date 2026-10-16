"""Approve one exact machine request through the Linux desktop's Chromium.

The same contract as the macOS Safari driver (``machine_browser_approval``):
find the approval tab the installer opened, require an exact same-origin
exact-code URL, revalidate it before pressing the visible control, and accept
only a same-origin navigation or visible connected confirmation in that tab. The host side is the stdlib
program in ``linux_desktop_chromium``.
"""

from __future__ import annotations

import json
from pathlib import Path
import shlex
from typing import Any

from yoke_contracts.machine_qa_failures import bounded_machine_qa_diagnostic
from yoke_harness import linux_desktop_chromium, linux_devtools_page
from yoke_harness.linux_desktop_session import desktop_command, ensure_desktop
from yoke_harness.machine_browser_approval import (
    APPROVE_CONTROL_LABEL,
    CONNECTED_CONFIRMATION,
    BrowserApprovalResult,
    approval_outcome,
    approval_tab_urls,
    approval_url,
)
from yoke_harness.ssh_mac_sign_in_apps import SIGN_IN_APP_QUIT_NOT_PROVED
from yoke_harness.test_machine_types import HostActionResult

BROWSER = "Chromium"
NO_DESKTOP = "headless_linux_browser_approval_unavailable"
NO_DESKTOP_RECOVERY = (
    "Browser approval on Linux runs in the test user's XFCE desktop Chromium. "
    "Provision the desktop and store desktop_password as "
    "docs/packs/machine-qa/linux-host-provisioning.md describes, then rerun."
)
HELPER_UNREADABLE = "linux_desktop_chromium_unreadable"
_HOST_TIMEOUT_SECONDS = 90
_DEVTOOLS_IMPORT = "from yoke_harness.linux_devtools_page import DevToolsPage"
_CONFIRMATION_IMPORT = (
    "from yoke_harness.machine_browser_approval import CONNECTED_CONFIRMATION"
)


def _host(control: Any, *arguments: str, desktop: bool = True) -> dict[str, Any]:
    program = "\n".join(
        [
            Path(linux_devtools_page.__file__).read_text(),
            f"CONNECTED_CONFIRMATION = {json.dumps(CONNECTED_CONFIRMATION)}",
            Path(linux_desktop_chromium.__file__)
            .read_text()
            .replace(_DEVTOOLS_IMPORT, "")
            .replace(_CONFIRMATION_IMPORT, ""),
            "main()\n",
        ]
    )
    argv = ["/usr/bin/python3", "-c", program, *arguments]
    if desktop:
        result = desktop_command(control, argv, timeout=_HOST_TIMEOUT_SECONDS)
    else:
        result = control._run(shlex.join(argv), timeout=_HOST_TIMEOUT_SECONDS)
    try:
        payload = json.loads(result.stdout.strip().splitlines()[-1])
        if not isinstance(payload, dict):
            raise ValueError
    except (ValueError, IndexError):
        return {
            "ok": False,
            "reason": HELPER_UNREADABLE,
            "exit_code": result.returncode,
            "stderr": bounded_machine_qa_diagnostic(
                result.stderr, getattr(control, "secret_values", ())
            ),
            "recovery": "The desktop Chromium helper exited "
            + str(result.returncode)
            + " without a receipt; restore SSH and python3 on the host, then rerun.",
        }
    return payload


def prepare_desktop_chromium(control: Any) -> HostActionResult:
    """Start the desktop and its debuggable Chromium before the installer runs."""
    try:
        receipt = ensure_desktop(control)
        prepared = _host(control, "prepare")
    except RuntimeError as exc:
        return HostActionResult(
            False, {"recovery": f"{exc} {NO_DESKTOP_RECOVERY}"}, NO_DESKTOP
        )
    if not prepared.get("ok"):
        return HostActionResult(
            False, {"recovery": prepared.get("recovery")}, prepared.get("reason")
        )
    return HostActionResult(
        True,
        {
            "environment": receipt["environment"],
            "desktop_session": receipt["desktop_session"],
            "chromium": prepared["chromium"],
        },
    )


def approve_machine_in_desktop_chromium(
    control: Any, *, verification_url: str, user_code: str
) -> BrowserApprovalResult:
    """Press the approval button only in the exact installer-opened tab."""
    try:
        expected_url, expected_origin = approval_url(verification_url, user_code)
    except ValueError:
        return BrowserApprovalResult(False, {}, "machine_browser_context_invalid")
    allowed_urls = [expected_url]
    try:
        tabs = _host(control, "tabs", expected_origin)
        if tabs.get("ok"):
            allowed_urls = approval_tab_urls(expected_url, user_code, tabs["urls"])
            outcome = _host(
                control,
                "approve",
                json.dumps(allowed_urls),
                APPROVE_CONTROL_LABEL,
            )
        else:
            outcome = tabs
    except RuntimeError as exc:
        outcome = {"ok": False, "reason": NO_DESKTOP, "recovery": str(exc)}
    if not outcome.get("ok"):
        return BrowserApprovalResult(
            False,
            {
                "browser": BROWSER,
                "reason": outcome.get("reason"),
                "recovery": outcome.get("recovery"),
            },
            "machine_browser_automation_unavailable",
        )
    return approval_outcome(
        browser=BROWSER,
        state=outcome.get("state", ""),
        starting_url=outcome.get("starting_url", ""),
        result_url=outcome.get("result_url", ""),
        allowed_urls=allowed_urls,
        expected_origin=expected_origin,
    )


def quit_desktop_chromium(control: Any) -> HostActionResult:
    """Quit Chromium so its cookie store is on disk before capture or reset."""
    stopped = _host(control, "quit", desktop=False)
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


__all__ = [
    "NO_DESKTOP",
    "approve_machine_in_desktop_chromium",
    "prepare_desktop_chromium",
    "quit_desktop_chromium",
]
