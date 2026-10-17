"""Approve one exact machine request through a visible Safari tab."""

from __future__ import annotations

import json

from yoke_harness.machine_browser_approval import (
    APPROVE_CONTROL_LABEL,
    CONNECTED_CONFIRMATION,
    BrowserApprovalResult,
    approval_outcome,
    approval_tab_urls,
    approval_url,
    missing_approval_tab,
)
from yoke_harness.ssh_mac_terminal_app import RunRemote, run_osascript


_RESULT_SEPARATOR = "|"
# Press (up to 20 polls) plus confirmation (40 polls, one window walk each);
# a walk takes seconds on an older Mac, so the shared 20 s bound is too short.
_APPROVAL_TIMEOUT_SECONDS = 90


def _script(*, allowed_urls: list[str]) -> list[str]:
    allowed = "{" + ", ".join(json.dumps(url) for url in allowed_urls) + "}"
    label = json.dumps(APPROVE_CONTROL_LABEL)
    confirmation = json.dumps(CONNECTED_CONFIRMATION)
    return [
        f"set allowedURLs to {allowed}",
        f"set buttonLabel to {label}",
        "set matchedWindow to missing value",
        "set matchedTab to missing value",
        'tell application "Safari"',
        "repeat with browserWindow in windows",
        "repeat with browserTab in tabs of browserWindow",
        "set tabURL to URL of browserTab as text",
        "if tabURL is in allowedURLs then",
        "set current tab of browserWindow to browserTab",
        "set index of browserWindow to 1",
        "set matchedWindow to browserWindow",
        "set matchedTab to browserTab",
        "set matchedStartingURL to tabURL",
        "exit repeat",
        "end if",
        "end repeat",
        "if matchedWindow is not missing value then exit repeat",
        "end repeat",
        'if matchedWindow is missing value then return "browser_tab_missing"',
        "activate",
        'if (URL of matchedTab as text) is not matchedStartingURL then return "browser_tab_changed"',
        "end tell",
        "delay 0.2",
        "set pressedApproval to false",
        'tell application "System Events"',
        'tell process "Safari"',
        "set frontmost to true",
        "repeat 20 times",
        "try",
        "set allElements to entire contents of front window",
        "repeat with candidate in allElements",
        "try",
        'if (role of candidate as text) is "AXButton" and '
        "(name of candidate as text) is buttonLabel then",
        'perform action "AXPress" of candidate',
        "set pressedApproval to true",
        "exit repeat",
        "end if",
        "end try",
        "end repeat",
        "end try",
        "if pressedApproval then exit repeat",
        "delay 0.25",
        "end repeat",
        "end tell",
        "end tell",
        'if not pressedApproval then return "approval_control_missing"',
        # The approval page redraws in place, so its heading is the only
        # confirmation. Walk the window once per poll: re-reading `entire
        # contents` per element is too slow on an older Mac to finish in time.
        "set resultURL to matchedStartingURL",
        'set confirmed to "approved_in_place|" & matchedStartingURL & "|" & matchedStartingURL',
        'set lastError to ""',
        "set startedAt to current date",
        'tell application "Safari"',
        "repeat 40 times",
        "delay 0.25",
        "try",
        "set resultURL to URL of matchedTab as text",
        'if resultURL is not matchedStartingURL then return "approved|" & matchedStartingURL & "|" & resultURL',
        "set current tab of matchedWindow to matchedTab",
        "set index of matchedWindow to 1",
        "on error errText",
        "set lastError to errText",
        "end try",
        'tell application "System Events"',
        'tell process "Safari"',
        "try",
        "set pageElements to entire contents of front window",
        "repeat with candidate in pageElements",
        "try",
        'if (role of candidate as text) is in {"AXHeading", "AXStaticText"} then',
        "try",
        f"if (value of candidate as text) is {confirmation} then return confirmed",
        "end try",
        "try",
        f"if (name of candidate as text) is {confirmation} then return confirmed",
        "end try",
        "try",
        f"if (title of candidate as text) is {confirmation} then return confirmed",
        "end try",
        "end if",
        "end try",
        "end repeat",
        "on error errText",
        "set lastError to errText",
        "end try",
        "end tell",
        "end tell",
        "end repeat",
        "end tell",
        'return "approval_navigation_missing|" & matchedStartingURL & "|" & '
        'resultURL & "|" & (((current date) - startedAt) as text) & "|" & lastError',
    ]


def approve_machine_in_safari(
    run: RunRemote,
    *,
    verification_url: str,
    user_code: str,
) -> BrowserApprovalResult:
    """Press the approval button only in the exact wizard-opened Safari tab."""
    try:
        expected_url, expected_origin = approval_url(verification_url, user_code)
    except ValueError:
        return BrowserApprovalResult(False, {}, "machine_browser_context_invalid")
    tabs = run_osascript(
        run,
        [
            'tell application "Safari"',
            'set tabURLs to ""',
            "repeat with browserWindow in windows",
            "repeat with browserTab in tabs of browserWindow",
            "set tabURLs to tabURLs & (URL of browserTab as text) & linefeed",
            "end repeat",
            "end repeat",
            "return tabURLs",
            "end tell",
        ],
    )
    if tabs.returncode:
        return BrowserApprovalResult(
            False, {"browser": "Safari"}, "machine_browser_automation_unavailable"
        )
    allowed_urls = approval_tab_urls(expected_url, user_code, tabs.stdout.splitlines())
    result = run_osascript(
        run, _script(allowed_urls=allowed_urls), timeout=_APPROVAL_TIMEOUT_SECONDS
    )
    if result.returncode:
        return BrowserApprovalResult(
            False,
            {"browser": "Safari"},
            "machine_browser_automation_unavailable",
        )
    fields = result.stdout.strip().split(_RESULT_SEPARATOR, 4)
    state, starting_url, result_url, elapsed, last_error = fields + [""] * (
        5 - len(fields)
    )
    if state == "browser_tab_missing":
        return missing_approval_tab(
            browser="Safari",
            expected_origin=expected_origin,
            user_code=user_code,
            observed=tabs.stdout.splitlines(),
        )
    outcome = approval_outcome(
        browser="Safari",
        state=state,
        starting_url=starting_url,
        result_url=result_url,
        allowed_urls=allowed_urls,
        expected_origin=expected_origin,
    )
    if state != "approval_navigation_missing":
        return outcome
    # Where the confirmation poll stopped, so a false failure is diagnosable.
    return BrowserApprovalResult(
        False,
        {
            **outcome.evidence,
            "observed_url": result_url,
            "confirmation_wait_seconds": int(elapsed) if elapsed.isdigit() else None,
            "last_error": last_error[:300] or None,
        },
        outcome.error_code,
    )


__all__ = ["BrowserApprovalResult", "approve_machine_in_safari"]
