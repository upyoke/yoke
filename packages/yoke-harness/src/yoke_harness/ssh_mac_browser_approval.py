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
)
from yoke_harness.ssh_mac_terminal_app import RunRemote, run_osascript


_RESULT_SEPARATOR = "|"


def _script(*, allowed_urls: list[str]) -> list[str]:
    allowed = "{" + ", ".join(json.dumps(url) for url in allowed_urls) + "}"
    label = json.dumps(APPROVE_CONTROL_LABEL)
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
        'tell application "Safari"',
        "repeat 40 times",
        "delay 0.25",
        "try",
        "set resultURL to URL of matchedTab as text",
        'if resultURL is not matchedStartingURL then return "approved|" & matchedStartingURL & "|" & resultURL',
        "set current tab of matchedWindow to matchedTab",
        "set index of matchedWindow to 1",
        'tell application "System Events"',
        'tell process "Safari"',
        "repeat with pageArea in entire contents of front window",
        'if (role of pageArea as text) is "AXWebArea" then',
        "repeat with candidate in entire contents of pageArea",
        "try",
        'if (role of candidate as text) is in {"AXHeading", "AXStaticText"} then',
        f"if (name of candidate as text) is {json.dumps(CONNECTED_CONFIRMATION)} or "
        f"(value of candidate as text) is {json.dumps(CONNECTED_CONFIRMATION)} then",
        'return "approved_in_place|" & matchedStartingURL & "|" & resultURL',
        "end if",
        "end if",
        "end try",
        "end repeat",
        "end if",
        "end repeat",
        "end tell",
        "end tell",
        "end try",
        "end repeat",
        "end tell",
        'return "approval_navigation_missing"',
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
    result = run_osascript(run, _script(allowed_urls=allowed_urls))
    if result.returncode:
        return BrowserApprovalResult(
            False,
            {"browser": "Safari"},
            "machine_browser_automation_unavailable",
        )
    state, _, navigation = result.stdout.strip().partition(_RESULT_SEPARATOR)
    starting_url, _, result_url = navigation.partition(_RESULT_SEPARATOR)
    return approval_outcome(
        browser="Safari",
        state=state,
        starting_url=starting_url,
        result_url=result_url,
        allowed_urls=allowed_urls,
        expected_origin=expected_origin,
    )


__all__ = ["BrowserApprovalResult", "approve_machine_in_safari"]
