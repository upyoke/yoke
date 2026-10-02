"""What an unreadable plan-limit reason establishes, and the recovery it earns.

A window that could not be read carries the probe's own reason. That reason
already separates a rejected or missing sign-in from a throttled read and
from a read that simply failed, and each calls for a different response:
only the first is repaired by signing in again. This module is the one place
that turns a reason into operator guidance, so the Machines card and the
steering report's plan-limits table cannot say different things about the
same reading.

The guidance asserts only what the reason establishes. A plan-limit read is
informational and never gates a launch, so no reason here says a launch will
fail, and only a credential reason says the surface needs a sign-in.
"""

from __future__ import annotations

from typing import Any, Mapping

from yoke_contracts.session_control.plan_limits import RELAY_PREDATES_WINDOWS_REASON

# A probe that tried two sources joins their reasons with this separator.
REASON_SEPARATOR = "+"

CREDENTIAL_GUIDANCE = (
    "the CLI's stored sign-in is missing or was rejected by the vendor; "
    "re-authenticate the CLI on that machine"
)
THROTTLED_GUIDANCE = (
    "the vendor throttled the limits check; the surface is not known to be "
    "signed out; it retries on the next refresh"
)
RELAY_UPDATE_GUIDANCE = (
    "this machine's relay predates per-window readings; update the relay"
)
READ_FAILED_GUIDANCE = "the limits read failed; it retries on the next refresh"

_CREDENTIAL_REASON = "stale_credential"
_CREDENTIAL_REASON_PREFIX = "codex_auth_"
_THROTTLED_REASON = "http_429"


def _is_credential(part: str) -> bool:
    return part == _CREDENTIAL_REASON or part.startswith(_CREDENTIAL_REASON_PREFIX)


def unreadable_guidance(reason: str | None) -> str:
    """Return the guidance one unreadable reason earns.

    A joined reason is read part by part, and the most specific finding
    wins: a credential problem on either source needs a sign-in whatever
    the other source said, and a throttle outranks a plain failed read.
    """
    parts = [part for part in str(reason or "").split(REASON_SEPARATOR) if part]
    if any(_is_credential(part) for part in parts):
        return CREDENTIAL_GUIDANCE
    if _THROTTLED_REASON in parts:
        return THROTTLED_GUIDANCE
    if RELAY_PREDATES_WINDOWS_REASON in parts:
        return RELAY_UPDATE_GUIDANCE
    return READ_FAILED_GUIDANCE


def unreadable_note(reason: str | None) -> str:
    """The reason beside its guidance, as one line for a report cell."""
    return f"{reason or 'unreadable'} — {unreadable_guidance(reason)}"


def with_unreadable_guidance(
    plan_limits: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Copy sanitized readings, adding ``guidance`` to each unreadable window."""
    guided: dict[str, dict[str, Any]] = {}
    for surface, reading in plan_limits.items():
        windows = []
        for window in reading.get("windows") or ():
            entry = dict(window)
            if entry.get("status") != "ok":
                entry["guidance"] = unreadable_guidance(entry.get("reason"))
            windows.append(entry)
        guided[surface] = {**reading, "windows": windows}
    return guided


__all__ = [
    "CREDENTIAL_GUIDANCE",
    "READ_FAILED_GUIDANCE",
    "REASON_SEPARATOR",
    "RELAY_UPDATE_GUIDANCE",
    "THROTTLED_GUIDANCE",
    "unreadable_guidance",
    "unreadable_note",
    "with_unreadable_guidance",
]
