"""Plan-limit parsers and the relay cache that keeps vendor calls off the 60s poll."""

from __future__ import annotations

from pathlib import Path

from yoke_contracts.session_control.plan_limits import (
    parse_claude_usage,
    parse_codex_rate_limits,
    parse_cursor_usage,
    sanitize_plan_limits,
    unknown_reading,
)
from yoke_harness import session_relay_plan_limits as limits


NOW = "2026-08-30T01:00:00Z"


def test_claude_parser_reads_limits_array_and_picks_the_tightest_window() -> None:
    reading = parse_claude_usage(
        {
            "claudeAiOauth": {
                "subscriptionType": "max",
                "rateLimitTier": "default_claude_max_20x",
            }
        },
        {
            "limits": [
                {
                    "kind": "session",
                    "percent": 9,
                    "resets_at": "2026-08-30T03:00:00Z",
                },
                {
                    "kind": "weekly_all",
                    "percent": 30,
                    "resets_at": "2026-09-04T01:00:00Z",
                },
            ]
        },
        observed_at=NOW,
    )
    assert reading["status"] == "ok"
    assert reading["plan_tier"] == "max"
    assert reading["window_kind"] == "rolling_7d"
    assert reading["remaining_percent"] == 70.0
    assert reading["resets_at"] == "2026-09-04T01:00:00Z"


def test_codex_parser_reads_the_primary_codex_bucket() -> None:
    reading = parse_codex_rate_limits(
        {
            "rateLimits": {"planType": "pro"},
            "rateLimitsByLimitId": {
                "codex": {
                    "planType": "pro",
                    "primary": {
                        "usedPercent": 1,
                        "windowDurationMins": 10080,
                        "resetsAt": 1788643692,
                    },
                }
            },
        },
        observed_at=NOW,
    )
    assert reading["status"] == "ok"
    assert reading["plan_tier"] == "pro"
    assert reading["window_kind"] == "rolling_7d"
    assert reading["remaining_percent"] == 99.0
    assert reading["resets_at"] == "2026-09-05T21:28:12Z"


def test_codex_parser_reshapes_the_http_mirror_primary_window() -> None:
    reading = parse_codex_rate_limits(
        {
            "plan_type": "pro",
            "rate_limit": {
                "primary_window": {
                    "used_percent": 1,
                    "limit_window_seconds": 604800,
                    "reset_at": 1788643692,
                }
            },
        },
        observed_at=NOW,
    )
    assert reading["status"] == "ok"
    assert reading["plan_tier"] == "pro"
    assert reading["window_kind"] == "rolling_7d"
    assert reading["remaining_percent"] == 99.0
    assert reading["resets_at"] == "2026-09-05T21:28:12Z"


def test_cursor_parser_labels_the_monthly_billing_window() -> None:
    reading = parse_cursor_usage(
        {"planInfo": {"planName": "Ultra"}},
        {
            "billingCycleEnd": "1788742804000",
            "planUsage": {"totalPercentUsed": 70.94885714285715},
        },
        observed_at=NOW,
    )
    assert reading["status"] == "ok"
    assert reading["plan_tier"] == "Ultra"
    assert reading["window_kind"] == "monthly"
    assert round(reading["remaining_percent"], 2) == 29.05
    assert reading["resets_at"] == "2026-09-07T01:00:04Z"


def test_sanitize_drops_token_bearing_keys() -> None:
    cleaned = sanitize_plan_limits(
        {
            "claude-cli": {
                "status": "ok",
                "window_kind": "rolling_5h",
                "remaining_percent": 80,
                "accessToken": "secret-token",
                "Authorization": "Bearer secret",
            }
        }
    )
    assert "accessToken" not in cleaned["claude-cli"]
    assert "Authorization" not in str(cleaned)


def test_a_raising_probe_names_the_class_that_raised(
    monkeypatch, tmp_path: Path
) -> None:
    """A probe that blows up must not read the same as one that answered badly."""

    def _boom(*, observed_at: str) -> dict:
        raise RuntimeError("vendor client exploded")

    monkeypatch.setitem(limits._PROBES, "claude-cli", _boom)

    readings = limits.observe_plan_limits(
        ("claude-cli",), state_dir=tmp_path, now=1_000.0, clock=lambda: NOW
    )

    assert readings["claude-cli"]["reason"] == "probe_raised_RuntimeError"


def test_fresh_cache_skips_a_second_probe(monkeypatch, tmp_path: Path) -> None:
    calls: list[str] = []

    def _fake(surface: str, observed_at: str) -> dict:
        calls.append(surface)
        return unknown_reading(surface, "stale_credential", observed_at=observed_at)

    monkeypatch.setattr(limits, "_probe_one", _fake)
    first = limits.observe_plan_limits(
        ("claude-cli",), state_dir=tmp_path, now=1_000.0, clock=lambda: NOW
    )
    second = limits.observe_plan_limits(
        ("claude-cli",), state_dir=tmp_path, now=1_060.0, clock=lambda: NOW
    )
    third = limits.observe_plan_limits(
        ("claude-cli",),
        state_dir=tmp_path,
        now=1_000.0 + limits.PLAN_LIMIT_REFRESH_SECONDS + 1,
        clock=lambda: NOW,
    )
    assert calls == ["claude-cli", "claude-cli"]
    assert first["claude-cli"]["reason"] == "stale_credential"
    assert second["claude-cli"]["reason"] == "stale_credential"
    assert third["claude-cli"]["reason"] == "stale_credential"
