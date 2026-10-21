"""Pick the declared account in Safari's Google account chooser tab.

``machine_account_chooser`` decides which tab and account qualify; this module
only reads the accounts the visible chooser lists and presses the chosen one
through the accessibility tree, then waits for the tab to settle on the
approval origin.
"""

from __future__ import annotations

import json

from yoke_harness.machine_account_chooser import (
    CHOOSER_WAIT_SECONDS,
    DeclaredAccounts,
    chooser_outcome,
    pick_account,
)
from yoke_harness.machine_browser_approval import BrowserApprovalResult
from yoke_harness.ssh_mac_terminal_app import RunRemote, run_osascript


BROWSER = "Safari"
_TIMEOUT_SECONDS = 90
_POLL_SECONDS = 0.25
#: Polls the tab URL must stay unchanged on the origin before it counts.
_SETTLED_POLLS = 3


def _front_tab(chooser_url: str) -> list[str]:
    return [
        f"set chooserURL to {json.dumps(chooser_url)}",
        "set matchedWindow to missing value",
        'tell application "Safari"',
        "repeat with browserWindow in windows",
        "repeat with browserTab in tabs of browserWindow",
        "if (URL of browserTab as text) is chooserURL then",
        "set current tab of browserWindow to browserTab",
        "set index of browserWindow to 1",
        "set matchedWindow to browserWindow",
        "set matchedTab to browserTab",
        "exit repeat",
        "end if",
        "end repeat",
        "if matchedWindow is not missing value then exit repeat",
        "end repeat",
        'if matchedWindow is missing value then return "chooser_tab_changed|"',
        "activate",
        "end tell",
        "delay 0.2",
    ]


def _offered_script(chooser_url: str) -> list[str]:
    return [
        *_front_tab(chooser_url),
        'set offered to ""',
        'tell application "System Events"',
        'tell process "Safari"',
        "set frontmost to true",
        "repeat 20 times",
        "try",
        "repeat with candidate in (entire contents of front window)",
        "try",
        'if (role of candidate as text) is "AXStaticText" then',
        "set candidateText to (value of candidate as text)",
        'if candidateText contains "@" then set offered to offered & candidateText & linefeed',
        "end if",
        "end try",
        "end repeat",
        "end try",
        'if offered is not "" then exit repeat',
        f"delay {_POLL_SECONDS}",
        "end repeat",
        "end tell",
        "end tell",
        'return "offered" & linefeed & offered',
    ]


def _press_script(chooser_url: str, account: str, expected_origin: str) -> list[str]:
    origin = json.dumps(expected_origin + "/")
    sign_in = json.dumps(expected_origin + "/auth/")
    polls = int(CHOOSER_WAIT_SECONDS / _POLL_SECONDS)
    return [
        *_front_tab(chooser_url),
        f"set accountName to {json.dumps(account)}",
        "set pressed to false",
        'tell application "System Events"',
        'tell process "Safari"',
        "set frontmost to true",
        "repeat 20 times",
        "try",
        "repeat with candidate in (entire contents of front window)",
        "try",
        'if (role of candidate as text) is "AXStaticText" and '
        "(value of candidate as text) is accountName then",
        # The account row is the clickable ancestor of its email text.
        "set row to candidate",
        "repeat 5 times",
        'set row to value of attribute "AXParent" of row',
        'if (role of row as text) is in {"AXLink", "AXButton"} then',
        'perform action "AXPress" of row',
        "set pressed to true",
        "exit repeat",
        "end if",
        "end repeat",
        "if not pressed then",
        "click candidate",
        "set pressed to true",
        "end if",
        "end if",
        "end try",
        "if pressed then exit repeat",
        "end repeat",
        "end try",
        "if pressed then exit repeat",
        f"delay {_POLL_SECONDS}",
        "end repeat",
        "end tell",
        "end tell",
        'if not pressed then return "account_control_missing|"',
        "set lastURL to chooserURL",
        "set settled to 0",
        'tell application "Safari"',
        f"repeat {polls} times",
        f"delay {_POLL_SECONDS}",
        "try",
        "set currentURL to URL of matchedTab as text",
        f"if currentURL starts with {origin} and currentURL does not start with {sign_in} "
        "and currentURL is lastURL then",
        "set settled to settled + 1",
        f'if settled is {_SETTLED_POLLS} then return "arrived|" & currentURL',
        "else",
        "set settled to 0",
        "end if",
        "set lastURL to currentURL",
        "end try",
        "end repeat",
        "end tell",
        'return "choice_unconfirmed|" & lastURL',
    ]


def choose_declared_account_in_safari(
    run: RunRemote,
    *,
    chooser_url: str,
    expected_origin: str,
    declared: DeclaredAccounts,
) -> BrowserApprovalResult:
    """Press the one declared account the chooser lists, then await the origin."""
    unavailable = BrowserApprovalResult(
        False, {"browser": BROWSER}, "machine_browser_automation_unavailable"
    )
    listed = run_osascript(run, _offered_script(chooser_url), timeout=_TIMEOUT_SECONDS)
    if listed.returncode:
        return unavailable
    lines = listed.stdout.strip().splitlines()
    if not lines or lines[0] != "offered":
        state = lines[0].partition("|")[0] if lines else ""
        return chooser_outcome(
            browser=BROWSER,
            state=state,
            account="",
            result_url="",
            expected_origin=expected_origin,
        )
    account, refusal = pick_account(
        browser=BROWSER,
        expected_origin=expected_origin,
        offered=lines[1:],
        declared=declared,
    )
    if refusal is not None:
        return refusal
    assert account is not None
    pressed = run_osascript(
        run,
        _press_script(chooser_url, account, expected_origin),
        timeout=_TIMEOUT_SECONDS,
    )
    if pressed.returncode:
        return unavailable
    state, _, result_url = pressed.stdout.strip().partition("|")
    return chooser_outcome(
        browser=BROWSER,
        state=state,
        account=account,
        result_url=result_url,
        expected_origin=expected_origin,
    )


__all__ = ["choose_declared_account_in_safari"]
