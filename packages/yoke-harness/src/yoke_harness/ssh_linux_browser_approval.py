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
import time
from urllib.parse import urlsplit, urlunsplit
from typing import Any

from yoke_contracts.machine_qa_failures import bounded_machine_qa_diagnostic
from yoke_harness import (
    linux_chromium_processes,
    linux_desktop_chromium,
    linux_devtools_page,
)
from yoke_harness.linux_desktop_session import desktop_command, ensure_desktop
from yoke_harness.machine_account_chooser import (
    CHOOSER_WAIT_SECONDS,
    DeclaredAccounts,
    account_chooser_url,
    chooser_outcome,
    pick_account,
)
from yoke_harness.machine_browser_approval import (
    APPROVE_CONTROL_LABEL,
    CONNECTED_CONFIRMATION,
    BrowserApprovalResult,
    approval_outcome,
    approval_tab_urls,
    approval_url,
    missing_approval_tab,
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
            Path(linux_chromium_processes.__file__).read_text(),
            f"CONNECTED_CONFIRMATION = {json.dumps(CONNECTED_CONFIRMATION)}",
            Path(linux_desktop_chromium.__file__)
            .read_text()
            .replace(_DEVTOOLS_IMPORT, "")
            .replace(_CONFIRMATION_IMPORT, "")
            .replace(
                "from yoke_harness import linux_chromium_processes as native_processes",
                "",
            )
            .replace("native_processes.", ""),
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


def _choose_declared_account(
    control: Any, chooser_url: str, expected_origin: str, declared: DeclaredAccounts
) -> BrowserApprovalResult:
    listed = _host(control, "chooser-accounts", chooser_url)
    if not listed.get("ok") or listed.get("state") != "offered":
        return _host_outcome(listed, expected_origin)
    account, refusal = pick_account(
        browser=BROWSER,
        expected_origin=expected_origin,
        offered=[str(value) for value in listed.get("accounts") or []],
        declared=declared,
    )
    if refusal is not None:
        return refusal
    assert account is not None
    chosen = _host(
        control,
        "choose",
        chooser_url,
        account,
        expected_origin,
        str(CHOOSER_WAIT_SECONDS),
    )
    return _host_outcome(chosen, expected_origin, account)


def _host_outcome(
    reply: dict[str, Any], expected_origin: str, account: str = ""
) -> BrowserApprovalResult:
    if not reply.get("ok"):
        return BrowserApprovalResult(
            False,
            {
                "browser": BROWSER,
                "reason": reply.get("reason"),
                "recovery": reply.get("recovery"),
            },
            "machine_browser_automation_unavailable",
        )
    return chooser_outcome(
        browser=BROWSER,
        state=str(reply.get("state") or ""),
        account=account,
        result_url=str(reply.get("result_url") or ""),
        expected_origin=expected_origin,
    )


def approve_machine_in_desktop_chromium(
    control: Any,
    *,
    verification_url: str,
    user_code: str,
    declared_accounts: DeclaredAccounts,
) -> BrowserApprovalResult:
    """Press the approval button only in the exact installer-opened tab.

    A tab stopped at Google's account chooser on its way to the approval page
    is first sent on with the project's declared account.
    """
    try:
        expected_url, expected_origin = approval_url(verification_url, user_code)
    except ValueError:
        return BrowserApprovalResult(False, {}, "machine_browser_context_invalid")
    allowed_urls = [expected_url]
    chooser_evidence: dict[str, Any] = {}
    try:
        deadline = time.monotonic() + linux_desktop_chromium.TAB_WAIT_SECONDS
        while True:
            tabs = _host(control, "tabs", expected_origin)
            if not tabs.get("ok"):
                outcome = tabs
                break
            allowed_urls = approval_tab_urls(expected_url, user_code, tabs["urls"])
            if any(url in allowed_urls for url in tabs["urls"]):
                outcome = _host(
                    control,
                    "approve",
                    json.dumps(allowed_urls),
                    APPROVE_CONTROL_LABEL,
                )
                break
            # A request-specific route with a rejected query is a navigation
            # refusal, not an unrelated tab still waiting for this request.
            invalid_route = False
            for url in tabs["urls"]:
                try:
                    parsed = urlsplit(url)
                    base = urlunsplit(parsed._replace(query=""))
                except ValueError:
                    continue
                if base != expected_url and base in approval_tab_urls(
                    expected_url, user_code, [base]
                ):
                    invalid_route = True
            if invalid_route:
                outcome = {"ok": True, "state": "approval_navigation_missing"}
                break
            chooser_url = account_chooser_url(tabs["urls"], expected_origin)
            if chooser_url is not None and not chooser_evidence:
                chosen = _choose_declared_account(
                    control, chooser_url, expected_origin, declared_accounts
                )
                if not chosen.ok:
                    return chosen
                chooser_evidence = chosen.evidence
                deadline = time.monotonic() + linux_desktop_chromium.TAB_WAIT_SECONDS
                continue
            if time.monotonic() >= deadline:
                outcome = {"ok": True, "state": "browser_tab_missing"}
                break
            time.sleep(linux_desktop_chromium.POLL_SECONDS)
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
    result = approval_outcome(
        browser=BROWSER,
        state=outcome.get("state", ""),
        starting_url=outcome.get("starting_url", ""),
        result_url=outcome.get("result_url", ""),
        allowed_urls=allowed_urls,
        expected_origin=expected_origin,
    )
    if outcome.get("state") == "browser_tab_missing":
        result = missing_approval_tab(
            browser=BROWSER,
            expected_origin=expected_origin,
            user_code=user_code,
            observed=tabs["urls"],
        )
    if not chooser_evidence:
        return result
    return BrowserApprovalResult(
        result.ok, {**result.evidence, **chooser_evidence}, result.error_code
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
