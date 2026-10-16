"""Paid extra usage is read beside the included windows and decides exhaustion.

The payloads are sanitized copies of real provider answers observed on
2026-10-16, so each parser is held to the shape the provider actually sends.
"""

from __future__ import annotations

import pytest

from yoke_contracts.session_control.extra_usage import (
    EXTRA_AVAILABLE,
    EXTRA_CAP_REACHED,
    EXTRA_DISABLED,
    EXTRA_STALE,
    EXTRA_UNAVAILABLE,
    EXTRA_UNKNOWN,
    RELAY_PREDATES_EXTRA_USAGE_REASON,
    extra_usage,
)
from yoke_contracts.session_control.model_billing_pools import pool_exhaustion
from yoke_contracts.session_control.plan_limit_parsers import (
    parse_claude_usage,
    parse_codex_rate_limits,
    parse_cursor_usage,
)
from yoke_contracts.session_control.plan_limits import (
    CURSOR_MODELS_SCOPE,
    CURSOR_OTHER_MODELS_SCOPE,
    plan_limit_window,
    sanitize_plan_limits,
)

NOW = "2026-10-16T12:20:00.000000Z"
STALE = "2026-10-16T12:10:00.000000Z"

CODEX_BUCKET = {
    "limitName": None,
    "primary": {
        "usedPercent": 100,
        "windowDurationMins": 10080,
        "resetsAt": 1792649776,
    },
    "secondary": None,
    "credits": {"hasCredits": True, "unlimited": False, "balance": "61206.8123050000"},
    "spendControlReached": False,
    "planType": "pro",
}
CODEX_MIRROR = {
    "plan_type": "pro",
    "rate_limit": {
        "primary_window": {
            "used_percent": 100,
            "limit_window_seconds": 604800,
            "reset_at": 1792649776,
        },
        "secondary_window": None,
    },
    "credits": {
        "has_credits": True,
        "unlimited": False,
        "overage_limit_reached": False,
        "balance": "61204.0588450000",
    },
    "spend_control": {"reached": False, "individual_limit": None},
}
CLAUDE_USAGE = {
    "limits": [{"kind": "session", "percent": 0, "resets_at": NOW, "scope": None}],
    "extra_usage": {
        "is_enabled": False,
        "monthly_limit": 100000,
        "used_credits": 0.0,
        "currency": "USD",
        "decimal_places": 2,
        "disabled_reason": "out_of_credits",
        "user_disabled": False,
        "spend_limit_reached": False,
    },
    "spend": {"balance": None},
}
CURSOR_USAGE = {
    "billingCycleEnd": "1794013204000",
    "planUsage": {"autoPercentUsed": 15.9, "apiPercentUsed": 100},
}


def _codex(bucket: dict) -> dict:
    return parse_codex_rate_limits(
        {"rateLimits": bucket, "rateLimitsByLimitId": {"codex": bucket}},
        observed_at=NOW,
    )["extra_usage"]


def test_codex_credits_are_available_with_their_published_balance() -> None:
    extra = _codex(CODEX_BUCKET)
    assert extra["status"] == EXTRA_AVAILABLE
    assert extra["balance"] == pytest.approx(61206.812305)
    assert extra["units"] == "Codex credits"
    assert extra["cap"] is None


def test_codex_mirror_carries_the_same_credit_facts() -> None:
    extra = parse_codex_rate_limits(CODEX_MIRROR, observed_at=NOW)["extra_usage"]
    assert extra["status"] == EXTRA_AVAILABLE
    assert extra["balance"] == pytest.approx(61204.058845)
    reached = {**CODEX_MIRROR, "spend_control": {"reached": True}}
    assert parse_codex_rate_limits(reached, observed_at=NOW)["extra_usage"][
        "status"
    ] == (EXTRA_CAP_REACHED)


@pytest.mark.parametrize(
    ("change", "status"),
    [
        ({"spendControlReached": True}, EXTRA_CAP_REACHED),
        ({"credits": {"hasCredits": False, "balance": "0"}}, EXTRA_UNAVAILABLE),
        ({"credits": {"unlimited": True}}, EXTRA_AVAILABLE),
        ({"credits": None}, EXTRA_UNKNOWN),
    ],
)
def test_codex_cap_and_funds_are_named(change: dict, status: str) -> None:
    assert _codex({**CODEX_BUCKET, **change})["status"] == status


def test_claude_out_of_credits_is_unavailable_and_keeps_cap_and_spend_apart() -> None:
    extra = parse_claude_usage({}, CLAUDE_USAGE, observed_at=NOW)["extra_usage"]
    assert extra["status"] == EXTRA_UNAVAILABLE
    assert extra["reason"] == "out_of_credits"
    assert (extra["cap"], extra["spent"], extra["units"]) == (1000.0, 0.0, "USD")
    # The cap is not funds: no balance is published, so none is invented.
    assert extra["balance"] is None


@pytest.mark.parametrize(
    ("change", "status"),
    [
        ({"is_enabled": True, "disabled_reason": None}, EXTRA_AVAILABLE),
        ({"spend_limit_reached": True}, EXTRA_CAP_REACHED),
        ({"disabled_reason": None, "user_disabled": True}, EXTRA_DISABLED),
        ({"is_enabled": None}, EXTRA_UNKNOWN),
    ],
)
def test_claude_extra_usage_states(change: dict, status: str) -> None:
    usage = {**CLAUDE_USAGE, "extra_usage": {**CLAUDE_USAGE["extra_usage"], **change}}
    assert parse_claude_usage({}, usage, observed_at=NOW)["extra_usage"]["status"] == (
        status
    )


@pytest.mark.parametrize(
    ("hard_limit", "status"),
    [
        ({"noUsageBasedAllowed": True}, EXTRA_DISABLED),
        ({}, EXTRA_AVAILABLE),
        ("http_404, at 2026-10-16T12:22:04+00:00", EXTRA_UNKNOWN),
    ],
)
def test_cursor_usage_based_pricing(hard_limit, status: str) -> None:
    reading = parse_cursor_usage(
        {}, CURSOR_USAGE, observed_at=NOW, hard_limit=hard_limit
    )
    assert reading["extra_usage"]["status"] == status


def test_a_stored_reading_without_extra_usage_names_the_old_relay() -> None:
    stored = sanitize_plan_limits(
        {"codex-cli": {"observed_at": NOW, "windows": [], "extra_usage": None}}
    )
    assert stored["codex-cli"]["extra_usage"]["reason"] == (
        RELAY_PREDATES_EXTRA_USAGE_REASON
    )


def _cursor_windows(cursor_models: float, other_models: float) -> list[dict]:
    return [
        plan_limit_window(
            window_kind="monthly",
            scope=scope,
            meter=f"planUsage.{scope}",
            remaining_percent=remaining,
            resets_at=None,
        )
        for scope, remaining in (
            (CURSOR_MODELS_SCOPE, cursor_models),
            (CURSOR_OTHER_MODELS_SCOPE, other_models),
        )
    ]


def _read(model: str, extra, observed_at=NOW, windows=None):
    return pool_exhaustion(
        "cursor-cli",
        model,
        windows if windows is not None else _cursor_windows(50.0, 0.0),
        extra_usage=extra,
        observed_at=observed_at,
        now=NOW,
    )


DISABLED = extra_usage(EXTRA_DISABLED, meter="m", reason="usage_based_pricing_off")


def test_an_empty_pool_is_exhausted_only_when_extra_usage_is_blocked() -> None:
    blocked = _read("claude-opus-5-5", DISABLED)
    assert blocked.exhausted and blocked.included_empty
    assert blocked.extra_label == "extra usage disabled (usage_based_pricing_off)"

    allowed = _read("claude-opus-5-5", extra_usage(EXTRA_AVAILABLE, meter="m"))
    assert not allowed.exhausted and allowed.included_empty
    assert allowed.extra_status == EXTRA_AVAILABLE


@pytest.mark.parametrize(
    ("extra", "observed_at", "status"),
    [
        (None, NOW, EXTRA_UNKNOWN),
        (extra_usage(EXTRA_UNKNOWN, meter="m", reason="http_503"), NOW, EXTRA_UNKNOWN),
        (DISABLED, STALE, EXTRA_STALE),
        (DISABLED, None, EXTRA_STALE),
    ],
)
def test_unproven_extra_usage_never_declares_exhaustion(extra, observed_at, status):
    reading = _read("claude-opus-5-5", extra, observed_at)
    assert not reading.exhausted
    assert reading.included_empty
    assert reading.extra_status == status


def test_extra_usage_never_moves_a_model_to_another_pool() -> None:
    # Composer bills Cursor Models, which still has headroom: the empty Other
    # Models pool cannot block it, and blocked extra usage changes nothing.
    reading = _read("composer-2.5", DISABLED)
    assert reading.pool == CURSOR_MODELS_SCOPE
    assert not reading.exhausted and not reading.included_empty
