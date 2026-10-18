"""Paid usage past a plan's included allowance, read beside the included windows.

An empty included window is not proof that an account cannot run. Codex
credits, Claude extra usage and Cursor usage-based pricing each let the
provider keep serving after the included allowance is spent. So every surface
reading carries one extra-usage fact beside its windows, and the pool rule
(:func:`yoke_contracts.session_control.model_billing_pools.pool_exhaustion`)
counts a pool exhausted only when its included window is empty and a fresh
extra-usage reading affirmatively says the provider will not bill past it.

Values only, never credentials. ``balance`` is funds the provider publishes as
a balance; it is never derived from cap minus spend. ``units`` names what the
numbers count, so numbers from two vendors are never compared or summed.
"""

from __future__ import annotations

import math
from typing import Any, Mapping

#: The provider will bill past the included allowance.
EXTRA_AVAILABLE = "available"
#: Extra usage is switched off for this account.
EXTRA_DISABLED = "disabled"
#: An applicable provider spending cap is reached.
EXTRA_CAP_REACHED = "cap_reached"
#: Extra usage is on, but the account has no funds to bill.
EXTRA_UNAVAILABLE = "unavailable"
#: The provider publishes no extra-usage fact for this account.
EXTRA_UNSUPPORTED = "unsupported"
#: The fact could not be read.
EXTRA_UNKNOWN = "unknown"
#: A stored reading too old to prove anything now. Derived, never stored.
EXTRA_STALE = "stale"

EXTRA_USAGE_STATUSES = frozenset(
    {
        EXTRA_AVAILABLE,
        EXTRA_DISABLED,
        EXTRA_CAP_REACHED,
        EXTRA_UNAVAILABLE,
        EXTRA_UNSUPPORTED,
        EXTRA_UNKNOWN,
    }
)
#: The statuses that prove the provider will refuse work past the allowance.
EXTRA_BLOCKING_STATUSES = frozenset(
    {EXTRA_DISABLED, EXTRA_CAP_REACHED, EXTRA_UNAVAILABLE}
)

# A heartbeat whose reading has windows but no extra-usage fact comes from a
# relay that predates this reading; updating that machine's relay is the fix.
RELAY_PREDATES_EXTRA_USAGE_REASON = "relay_predates_extra_usage"
EXTRA_USAGE_NOT_READ_REASON = "extra_usage_not_read"

_STRING_MAX = 128


def extra_usage(
    status: str,
    *,
    meter: str,
    enabled: bool | None = None,
    balance: float | None = None,
    spent: float | None = None,
    cap: float | None = None,
    units: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    """One extra-usage fact, exactly as the provider stated it."""
    return {
        "status": status,
        "enabled": enabled,
        "balance": balance,
        "spent": spent,
        "cap": cap,
        "units": units,
        "meter": meter,
        "reason": reason,
    }


def unknown_extra_usage(reason: str) -> dict[str, Any]:
    return extra_usage(EXTRA_UNKNOWN, meter="unknown", reason=reason)


def _amount(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(str(value))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number < 0:
        return None
    return number


def _clip(value: object) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text[:_STRING_MAX] or None


def sanitize_extra_usage(raw: object) -> dict[str, Any]:
    """Allowlisted values; a missing fact names the relay that predates it."""
    if raw is None:
        return unknown_extra_usage(RELAY_PREDATES_EXTRA_USAGE_REASON)
    if not isinstance(raw, Mapping):
        return unknown_extra_usage("extra_usage_unreadable")
    status = str(raw.get("status") or EXTRA_UNKNOWN)
    if status not in EXTRA_USAGE_STATUSES:
        status = EXTRA_UNKNOWN
    enabled = raw.get("enabled")
    return {
        "status": status,
        "enabled": enabled if isinstance(enabled, bool) else None,
        "balance": _amount(raw.get("balance")),
        "spent": _amount(raw.get("spent")),
        "cap": _amount(raw.get("cap")),
        "units": _clip(raw.get("units")),
        "meter": _clip(raw.get("meter")) or "unknown",
        "reason": _clip(raw.get("reason")),
    }


def _number(value: float) -> str:
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def extra_usage_label(extra: Mapping[str, Any] | None, status: str) -> str:
    """One concise phrase shared by previews, session status and reports."""
    extra = extra or {}
    units = f" {extra['units']}" if extra.get("units") else ""
    facts = []
    if extra.get("balance") is not None:
        facts.append(f"balance {_number(extra['balance'])}{units}")
    if extra.get("spent") is not None and extra.get("cap") is not None:
        facts.append(
            f"spent {_number(extra['spent'])} of {_number(extra['cap'])}{units}"
        )
    if status not in {EXTRA_AVAILABLE, EXTRA_STALE} and extra.get("reason"):
        facts.append(str(extra["reason"]))
    phrase = {
        EXTRA_AVAILABLE: "extra usage available",
        EXTRA_DISABLED: "extra usage disabled",
        EXTRA_CAP_REACHED: "extra usage cap reached",
        EXTRA_UNAVAILABLE: "extra usage unavailable",
        EXTRA_UNSUPPORTED: "extra usage unsupported",
        EXTRA_STALE: "extra usage reading stale",
    }.get(status, "extra usage unknown")
    return f"{phrase} ({', '.join(facts)})" if facts else phrase


__all__ = [
    "EXTRA_AVAILABLE",
    "EXTRA_BLOCKING_STATUSES",
    "EXTRA_CAP_REACHED",
    "EXTRA_DISABLED",
    "EXTRA_STALE",
    "EXTRA_UNAVAILABLE",
    "EXTRA_UNKNOWN",
    "EXTRA_UNSUPPORTED",
    "EXTRA_USAGE_NOT_READ_REASON",
    "EXTRA_USAGE_STATUSES",
    "RELAY_PREDATES_EXTRA_USAGE_REASON",
    "extra_usage",
    "extra_usage_label",
    "sanitize_extra_usage",
    "unknown_extra_usage",
]
