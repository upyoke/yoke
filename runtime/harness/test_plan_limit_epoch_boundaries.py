"""External provider epoch clocks preserve precision and optional absence."""

from __future__ import annotations

import pytest

from yoke_contracts.session_control.plan_limit_parsers import (
    parse_codex_rate_limits,
    parse_cursor_usage,
)


OBSERVED = "2026-08-30T01:00:00.000000Z"


def _reading(provider, epoch):
    if provider == "codex":
        return parse_codex_rate_limits(
            {
                "rateLimits": {
                    "primary": {
                        "usedPercent": 25,
                        "windowDurationMins": 300,
                        "resetsAt": epoch,
                    }
                }
            },
            observed_at=OBSERVED,
        )
    return parse_cursor_usage(
        {"planName": "ultra"},
        {"planUsage": {"autoPercentUsed": 25}, "billingCycleEnd": epoch},
        observed_at=OBSERVED,
    )


@pytest.mark.parametrize("provider", ["codex", "cursor"])
@pytest.mark.parametrize(
    "bad", [None, "", "unknown", float("nan"), float("inf"), -float("inf"), 1e100]
)
def test_invalid_optional_provider_reset_does_not_erase_usage_window(provider, bad):
    reading = _reading(provider, bad)
    assert reading["observed_at"] == OBSERVED
    assert len(reading["windows"]) == 1
    window = reading["windows"][0]
    assert window["remaining_percent"] == 75
    assert window["resets_at"] is None


@pytest.mark.parametrize("provider", ["codex", "cursor"])
@pytest.mark.parametrize(
    "seconds,expected",
    [
        (-0.123456, "1969-12-31T23:59:59.876544Z"),
        (0, "1970-01-01T00:00:00.000000Z"),
        (0.123456, "1970-01-01T00:00:00.123456Z"),
        (1.654321, "1970-01-01T00:00:01.654321Z"),
    ],
)
def test_provider_epoch_units_preserve_microseconds_and_epoch_zero(
    provider, seconds, expected
):
    epoch = seconds if provider == "codex" else seconds * 1000
    reading = _reading(provider, epoch)
    assert reading["windows"][0]["resets_at"] == expected
    assert reading["windows"][0]["remaining_percent"] == 75
