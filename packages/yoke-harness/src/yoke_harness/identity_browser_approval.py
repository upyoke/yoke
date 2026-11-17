"""Approve one exact machine request in the test machine's identity browser.

Every test machine keeps one login store: its identity profiles. The installer
opens its approval link through ``BROWSER`` (``yoke browser open``), so the
page lands in the operator identity's signed-in Chromium, which listens on a
loopback DevTools port. This driver runs the stdlib host program in
``identity_browser_devtools`` over the machine's SSH shell (Linux and macOS
``python3``): find the exact same-origin exact-code tab, revalidate it before
pressing the visible control, and accept only a same-origin navigation or the
visible connected confirmation in that tab. A tab that landed on a sign-in page
means the identity's login expired, and the refusal names the authorize command.
"""

from __future__ import annotations

from collections.abc import Callable
import json
from pathlib import Path
import shlex
import subprocess
import time
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from yoke_contracts.machine_browser_approval import (
    APPROVE_CONTROL_LABEL,
    CONNECTED_CONFIRMATION,
    BrowserApprovalResult,
    approval_outcome,
    approval_tab_urls,
    approval_url,
    missing_approval_tab,
)
from yoke_contracts.machine_qa_failures import bounded_machine_qa_diagnostic
from yoke_harness import identity_browser_devtools, linux_devtools_page

BROWSER = "Chromium"
HELPER_UNREADABLE = "identity_browser_helper_unreadable"
RunRemote = Callable[..., subprocess.CompletedProcess[str]]
_HOST_TIMEOUT_SECONDS = 90
_IMPORTS = (
    "from yoke_harness.linux_devtools_page import DevToolsPage  # host: prepended source",
    "from yoke_contracts.machine_browser_approval import CONNECTED_CONFIRMATION",
)


def host_program() -> str:
    """The self-contained stdlib program shipped to the test machine."""
    body = Path(identity_browser_devtools.__file__).read_text(encoding="utf-8")
    for line in _IMPORTS:
        body = body.replace(line, "")
    return "\n".join(
        [
            Path(linux_devtools_page.__file__).read_text(encoding="utf-8"),
            f"CONNECTED_CONFIRMATION = {json.dumps(CONNECTED_CONFIRMATION)}",
            body,
            "main()\n",
        ]
    )


def _host(run: RunRemote, *arguments: str, secrets=()) -> dict[str, Any]:
    argv = ["/usr/bin/python3", "-c", host_program(), *arguments]
    result = run(shlex.join(argv), timeout=_HOST_TIMEOUT_SECONDS)
    try:
        payload = json.loads(result.stdout.strip().splitlines()[-1])
        if not isinstance(payload, dict):
            raise ValueError
    except (ValueError, IndexError):
        return {
            "ok": False,
            "reason": HELPER_UNREADABLE,
            "exit_code": result.returncode,
            "stderr": bounded_machine_qa_diagnostic(result.stderr, secrets),
            "recovery": "The identity browser helper exited "
            + str(result.returncode)
            + " without a receipt; restore SSH and /usr/bin/python3 on the host, "
            "then rerun.",
        }
    return payload


def approve_machine_in_identity_browser(
    run: RunRemote,
    *,
    verification_url: str,
    user_code: str,
    reauthorize_command: str,
    secrets=(),
) -> BrowserApprovalResult:
    """Press the approval button only in the exact installer-opened tab."""
    try:
        expected_url, expected_origin = approval_url(verification_url, user_code)
    except ValueError:
        return BrowserApprovalResult(False, {}, "machine_browser_context_invalid")
    allowed_urls = [expected_url]
    tabs: dict[str, Any] = {"urls": []}
    deadline: float | None = None  # Starts at the first miss.
    while True:
        tabs = _host(run, "tabs", expected_origin, secrets=secrets)
        if not tabs.get("ok"):
            outcome = tabs
            break
        allowed_urls = approval_tab_urls(expected_url, user_code, tabs["urls"])
        if any(url in allowed_urls for url in tabs["urls"]):
            outcome = _host(
                run,
                "approve",
                json.dumps(allowed_urls),
                APPROVE_CONTROL_LABEL,
                secrets=secrets,
            )
            break
        # A request-specific route with a rejected query is a navigation
        # refusal, not an unrelated tab still waiting for this request.
        if any(_rejected_route(url, expected_url, user_code) for url in tabs["urls"]):
            outcome = {"ok": True, "state": "approval_navigation_missing"}
            break
        now = time.monotonic()
        if deadline is None:
            deadline = now + identity_browser_devtools.TAB_WAIT_SECONDS
        if now >= deadline:
            outcome = {"ok": True, "state": "browser_tab_missing"}
            break
        time.sleep(identity_browser_devtools.POLL_SECONDS)
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
    if outcome.get("state") == "browser_tab_missing":
        if not tabs.get("identity_browsers"):
            return BrowserApprovalResult(
                False,
                {
                    "browser": BROWSER,
                    "state": "identity_browser_not_running",
                    "recovery": "No identity browser is running on the test "
                    "machine, so the installer did not open its link through "
                    "`yoke browser open`. Set BROWSER for the installer as the "
                    "recipe does, check `" + reauthorize_command + "` has "
                    "signed the identity in, then rerun with a fresh request.",
                },
                "machine_browser_tab_missing",
            )
        return missing_approval_tab(
            browser=BROWSER,
            expected_origin=expected_origin,
            user_code=user_code,
            observed=tabs["urls"],
            reauthorize_command=reauthorize_command,
        )
    return approval_outcome(
        browser=BROWSER,
        state=outcome.get("state", ""),
        starting_url=outcome.get("starting_url", ""),
        result_url=outcome.get("result_url", ""),
        allowed_urls=allowed_urls,
        expected_origin=expected_origin,
    )


IDENTITY_BROWSER_CLOSE_NOT_PROVED = "test_machine_identity_browser_close_not_proved"


def close_identity_browsers(run: RunRemote, *, secrets=()) -> dict[str, Any]:
    """Close every identity browser gracefully before a capture or reset.

    Chromium writes its cookie store as it closes; a forced kill would drop
    the newest sign-in. Returns the helper receipt; ``ok`` False names why.
    """
    receipt = _host(run, "close", secrets=secrets)
    if receipt.get("ok") and not receipt.get("closed"):
        return {
            "ok": False,
            "reason": IDENTITY_BROWSER_CLOSE_NOT_PROVED,
            "still_running": receipt.get("still_running"),
            "recovery": "Close every identity browser window on the test "
            "machine's desktop, answering any prompt it shows, then retry. It was "
            "not force-quit, so its unsaved sign-ins are still in memory.",
        }
    return receipt


def _rejected_route(url: str, expected_url: str, user_code: str) -> bool:
    try:
        base = urlunsplit(urlsplit(url)._replace(query=""))
    except ValueError:
        return False
    return base != expected_url and base in approval_tab_urls(
        expected_url, user_code, [base]
    )


__all__ = [
    "BROWSER",
    "IDENTITY_BROWSER_CLOSE_NOT_PROVED",
    "close_identity_browsers",
    "approve_machine_in_identity_browser",
    "host_program",
]
