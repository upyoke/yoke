"""One exact-target approval contract shared by every native browser driver.

A driver lists the browser's open tab URLs, then presses the visible
"Approve machine" control only in a tab whose URL this contract allows, after
revalidating that the tab still shows it, and observes navigation or the visible
connected confirmation in that same tab. This module owns which tabs qualify and which outcomes count as
an approval; drivers own only how they talk to their browser.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any
from urllib.parse import parse_qs, urlsplit, urlunsplit

from yoke_contracts.machine_approval_coordinates import machine_approval_coordinates


APPROVE_CONTROL_LABEL = "Approve machine"
CONNECTED_CONFIRMATION = "Machine connected"
_REFUSED_STATUSES = frozenset(
    {"denied", "expired", "missing", "not_admin", "not_member", "used"}
)
#: Driver outcome states, shared by every driver, and their refusal codes.
STATE_ERRORS = {
    "browser_tab_missing": "machine_browser_tab_missing",
    "browser_tab_changed": "machine_browser_tab_changed",
    "approval_control_missing": "machine_browser_approval_control_missing",
    "approval_navigation_missing": "machine_browser_approval_navigation_missing",
}


@dataclass(frozen=True)
class BrowserApprovalResult:
    """Bounded result of one native browser approval attempt."""

    ok: bool
    evidence: dict[str, Any]
    error_code: str | None = None


def approval_url(verification_url: str, user_code: str) -> tuple[str, str]:
    """Return the complete approval URL and its origin, or raise ValueError."""
    coordinates = machine_approval_coordinates(verification_url, user_code)
    return coordinates.complete_uri, coordinates.origin


def _canonical_selection_query(query: str) -> bool:
    """Accept only the dashboard's single, unescaped selection parameter."""
    if not query:
        return True
    match = re.fullmatch(r"selection=(all|[1-9][0-9]*(?:,[1-9][0-9]*)*)", query)
    if match is None:
        return False
    members = match[1].split(",")
    return len(members) == len(set(members))


def approval_tab_urls(
    expected_url: str, user_code: str, observed: list[str]
) -> list[str]:
    """Allow the entry URL or its same-origin, exact-code organization route."""
    expected = urlsplit(expected_url)
    allowed = [expected_url]
    if expected.path != "/connect":
        return allowed
    for value in observed:
        try:
            parsed = urlsplit(value)
        except ValueError:
            continue
        parts = parsed.path.split("/")
        if (
            parsed.scheme == expected.scheme
            and parsed.netloc == expected.netloc
            and _canonical_selection_query(parsed.query)
            and not parsed.fragment
            and len(parts) == 5
            and parts[1] == "orgs"
            and parts[2] not in ("", ".", "..")
            and "%" not in parts[2]
            and parts[3:] == ["machine-approval", user_code]
            and value not in allowed
        ):
            allowed.append(value)
    return allowed


def _result_url(value: str, *, expected_origin: str) -> str | None:
    parsed = urlsplit(value)
    if f"{parsed.scheme}://{parsed.netloc}" != expected_origin:
        return None
    status = parse_qs(parsed.query).get("status", [""])[0]
    if status in _REFUSED_STATUSES:
        return None
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def approval_outcome(
    *,
    browser: str,
    state: str,
    starting_url: str,
    result_url: str,
    allowed_urls: list[str],
    expected_origin: str,
) -> BrowserApprovalResult:
    """Validate navigation or visible confirmation in the exact approved tab."""
    if state not in {"approved", "approved_in_place"}:
        return BrowserApprovalResult(
            False,
            {"browser": browser, "state": state or "empty"},
            STATE_ERRORS.get(state, "machine_browser_approval_failed"),
        )
    in_place = state == "approved_in_place"
    if (
        starting_url not in allowed_urls
        or not result_url
        or (result_url == starting_url) != in_place
    ):
        return BrowserApprovalResult(
            False, {"browser": browser}, "machine_browser_approval_navigation_missing"
        )
    safe_url = _result_url(result_url, expected_origin=expected_origin)
    if safe_url is None:
        return BrowserApprovalResult(
            False,
            {"browser": browser},
            "machine_browser_approval_destination_invalid",
        )
    return BrowserApprovalResult(
        True,
        {
            "browser": browser,
            "approval_entry": urlsplit(starting_url).path,
            "result_url": safe_url,
            "visible_control": APPROVE_CONTROL_LABEL,
            **({"visible_confirmation": CONNECTED_CONFIRMATION} if in_place else {}),
        },
    )


__all__ = [
    "APPROVE_CONTROL_LABEL",
    "CONNECTED_CONFIRMATION",
    "BrowserApprovalResult",
    "STATE_ERRORS",
    "approval_outcome",
    "approval_tab_urls",
    "approval_url",
]
