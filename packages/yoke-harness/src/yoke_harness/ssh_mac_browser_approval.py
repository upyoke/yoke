"""Approve one exact machine request through a visible Safari tab."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from yoke_harness.ssh_mac_terminal_app import RunRemote, run_osascript


_APPROVAL_PATHS = frozenset({"/connect", "/machine"})
_CODE_PATTERN = re.compile(r"[A-Z0-9]{4}-[A-Z0-9]{4}")
_REFUSED_STATUSES = frozenset(
    {"denied", "expired", "missing", "not_admin", "not_member", "used"}
)


@dataclass(frozen=True)
class BrowserApprovalResult:
    """Bounded result of one native browser approval attempt."""

    ok: bool
    evidence: dict[str, Any]
    error_code: str | None = None


def _approval_url(verification_url: str, user_code: str) -> tuple[str, str]:
    parsed = urlsplit(verification_url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in _APPROVAL_PATHS
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("browser approval URL is not a supported HTTPS entry")
    code = user_code.strip().upper()
    if _CODE_PATTERN.fullmatch(code) is None:
        raise ValueError("browser approval code has an invalid shape")
    complete = urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urlencode({"user_code": code}), "")
    )
    return complete, f"{parsed.scheme}://{parsed.netloc}"


def _script(*, expected_url: str) -> list[str]:
    expected = json.dumps(expected_url)
    label = json.dumps("Approve machine")
    return [
        f"set expectedURL to {expected}",
        f"set buttonLabel to {label}",
        "set matchedWindow to missing value",
        "set matchedTab to missing value",
        'tell application "Safari"',
        "repeat with browserWindow in windows",
        "repeat with browserTab in tabs of browserWindow",
        "if (URL of browserTab as text) is expectedURL then",
        "set current tab of browserWindow to browserTab",
        "set index of browserWindow to 1",
        "set matchedWindow to browserWindow",
        "set matchedTab to browserTab",
        "exit repeat",
        "end if",
        "end repeat",
        "if matchedWindow is not missing value then exit repeat",
        "end repeat",
        'if matchedWindow is missing value then return "browser_tab_missing"',
        "activate",
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
        'if resultURL is not expectedURL then return "approved" & tab & resultURL',
        "end try",
        "end repeat",
        "end tell",
        'return "approval_navigation_missing"',
    ]


def _result_url(value: str, *, expected_origin: str) -> str | None:
    parsed = urlsplit(value)
    if f"{parsed.scheme}://{parsed.netloc}" != expected_origin:
        return None
    status = parse_qs(parsed.query).get("status", [""])[0]
    if status in _REFUSED_STATUSES:
        return None
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def approve_machine_in_safari(
    run: RunRemote,
    *,
    verification_url: str,
    user_code: str,
) -> BrowserApprovalResult:
    """Press the approval button only in the exact wizard-opened Safari tab."""
    try:
        expected_url, expected_origin = _approval_url(verification_url, user_code)
    except ValueError:
        return BrowserApprovalResult(False, {}, "machine_browser_context_invalid")
    result = run_osascript(run, _script(expected_url=expected_url))
    if result.returncode:
        return BrowserApprovalResult(
            False,
            {"browser": "Safari"},
            "machine_browser_automation_unavailable",
        )
    state, separator, raw_url = result.stdout.strip().partition("\t")
    errors = {
        "browser_tab_missing": "machine_browser_tab_missing",
        "approval_control_missing": "machine_browser_approval_control_missing",
        "approval_navigation_missing": "machine_browser_approval_navigation_missing",
    }
    if state != "approved" or not separator:
        return BrowserApprovalResult(
            False,
            {"browser": "Safari", "state": state or "empty"},
            errors.get(state, "machine_browser_approval_failed"),
        )
    safe_url = _result_url(raw_url, expected_origin=expected_origin)
    if safe_url is None:
        return BrowserApprovalResult(
            False,
            {"browser": "Safari"},
            "machine_browser_approval_destination_invalid",
        )
    return BrowserApprovalResult(
        True,
        {
            "browser": "Safari",
            "approval_entry": urlsplit(expected_url).path,
            "result_url": safe_url,
            "visible_control": "Approve machine",
        },
    )


__all__ = ["BrowserApprovalResult", "approve_machine_in_safari"]
