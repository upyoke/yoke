"""Vendor payloads to one normalized extra-usage fact per surface.

Each parser reads only fields observed in the vendor's real answer and says
``unknown`` when they are absent. None of them derives a balance from a cap,
and none treats a cap as funds.

Observed shapes (sanitized, 2026-10-16):

- Codex ``account/rateLimits/read`` puts ``credits`` (``hasCredits``,
  ``unlimited``, ``balance`` as a decimal string of credits) and
  ``spendControlReached`` on each rate-limit bucket. The HTTP usage mirror
  carries the same facts as ``credits`` (``has_credits``, ``unlimited``,
  ``overage_limit_reached``, ``balance``) and ``spend_control.reached``.
- Claude's OAuth usage document carries ``extra_usage`` (``is_enabled``,
  ``monthly_limit`` and ``used_credits`` in minor currency units,
  ``decimal_places``, ``currency``, ``disabled_reason``, ``user_disabled``,
  ``spend_limit_reached``) and ``spend.balance`` as a minor-unit amount or
  null. These fields are undocumented, so their absence reads ``unknown``.
- Cursor's dashboard ``GetHardLimit`` answers ``noUsageBasedAllowed: true``
  when usage-based pricing is off. Connect JSON omits a false boolean, so an
  answered object without that flag means usage-based pricing is allowed.
  Cursor publishes no personal spend or balance here.
"""

from __future__ import annotations

from typing import Any, Mapping

from yoke_contracts.session_control.extra_usage import (
    EXTRA_AVAILABLE,
    EXTRA_CAP_REACHED,
    EXTRA_DISABLED,
    EXTRA_UNAVAILABLE,
    extra_usage,
    unknown_extra_usage,
)

CODEX_CREDIT_UNITS = "Codex credits"


def _decimal(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def parse_codex_extra_usage(bucket: Mapping[str, Any] | None) -> dict[str, Any]:
    """Codex credits are account-wide; read them from the account's bucket."""
    bucket = bucket if isinstance(bucket, Mapping) else {}
    credits = bucket.get("credits")
    if not isinstance(credits, Mapping):
        return unknown_extra_usage("codex_credits_unpublished")
    meter = "rateLimits.credits"
    balance = _decimal(credits.get("balance"))
    if bucket.get("spendControlReached") is True:
        return extra_usage(
            EXTRA_CAP_REACHED,
            meter="rateLimits.spendControlReached",
            balance=balance,
            units=CODEX_CREDIT_UNITS,
            reason="spend_control_reached",
        )
    if credits.get("unlimited") is True:
        return extra_usage(
            EXTRA_AVAILABLE, meter=meter, enabled=True, reason="unlimited"
        )
    has_credits = credits.get("hasCredits")
    if has_credits is True:
        return extra_usage(
            EXTRA_AVAILABLE,
            meter=meter,
            enabled=True,
            balance=balance,
            units=CODEX_CREDIT_UNITS,
        )
    if has_credits is False:
        return extra_usage(
            EXTRA_UNAVAILABLE,
            meter=meter,
            balance=balance,
            units=CODEX_CREDIT_UNITS,
            reason="no_credits",
        )
    return unknown_extra_usage("codex_credits_unreadable")


def codex_mirror_credits(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Reshape the HTTP mirror's credit facts into the app-server bucket keys."""
    out: dict[str, Any] = {}
    credits = payload.get("credits")
    if isinstance(credits, Mapping):
        out["credits"] = {
            "hasCredits": credits.get("has_credits"),
            "unlimited": credits.get("unlimited"),
            "balance": credits.get("balance"),
        }
    spend = payload.get("spend_control")
    reached = isinstance(spend, Mapping) and spend.get("reached") is True
    if reached or (
        isinstance(credits, Mapping) and credits.get("overage_limit_reached") is True
    ):
        out["spendControlReached"] = True
    return out


def _minor(value: object, places: int) -> float | None:
    number = _decimal(value)
    return None if number is None else number / (10**places)


def parse_claude_extra_usage(usage: Mapping[str, Any]) -> dict[str, Any]:
    extra = usage.get("extra_usage")
    if not isinstance(extra, Mapping):
        return unknown_extra_usage("claude_extra_usage_unpublished")
    places = extra.get("decimal_places")
    places = places if isinstance(places, int) and 0 <= places <= 6 else 2
    spend = usage.get("spend")
    balance_doc = spend.get("balance") if isinstance(spend, Mapping) else None
    balance = (
        _minor(balance_doc.get("amount_minor"), places)
        if isinstance(balance_doc, Mapping)
        else None
    )
    enabled = extra.get("is_enabled")
    facts = {
        "meter": "oauth_usage.extra_usage",
        "enabled": enabled if isinstance(enabled, bool) else None,
        "balance": balance,
        "spent": _minor(extra.get("used_credits"), places),
        "cap": _minor(extra.get("monthly_limit"), places),
        "units": str(extra["currency"]) if extra.get("currency") else None,
    }
    reason = extra.get("disabled_reason")
    reason = str(reason) if reason else None
    if extra.get("spend_limit_reached") is True:
        return extra_usage(EXTRA_CAP_REACHED, reason="spend_limit_reached", **facts)
    if enabled is True:
        return extra_usage(EXTRA_AVAILABLE, **facts)
    if enabled is not False:
        return unknown_extra_usage("claude_extra_usage_unreadable")
    if reason == "out_of_credits":
        return extra_usage(EXTRA_UNAVAILABLE, reason=reason, **facts)
    if extra.get("user_disabled") is True:
        reason = reason or "user_disabled"
    return extra_usage(EXTRA_DISABLED, reason=reason, **facts)


def parse_cursor_extra_usage(hard_limit: Mapping[str, Any] | str) -> dict[str, Any]:
    """Usage-based pricing on or off; a failed read names its own reason."""
    if isinstance(hard_limit, str):
        return unknown_extra_usage(hard_limit)
    meter = "GetHardLimit.noUsageBasedAllowed"
    if hard_limit.get("noUsageBasedAllowed") is True:
        return extra_usage(
            EXTRA_DISABLED,
            meter=meter,
            enabled=False,
            reason="usage_based_pricing_off",
        )
    return extra_usage(EXTRA_AVAILABLE, meter=meter, enabled=True)


__all__ = [
    "CODEX_CREDIT_UNITS",
    "codex_mirror_credits",
    "parse_claude_extra_usage",
    "parse_codex_extra_usage",
    "parse_cursor_extra_usage",
]
