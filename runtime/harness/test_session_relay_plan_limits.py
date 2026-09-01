"""Plan-limit parsers and the relay cache that keeps vendor calls off the 60s poll."""

from __future__ import annotations

from pathlib import Path

from yoke_contracts.session_control.plan_limit_parsers import (
    parse_claude_usage,
    parse_codex_rate_limits,
    parse_cursor_usage,
)
from yoke_contracts.session_control.plan_limits import (
    MAX_WINDOWS_PER_SURFACE,
    RELAY_PREDATES_WINDOWS_REASON,
    sanitize_plan_limits,
    unknown_reading,
)
from yoke_harness import session_relay_plan_limits as limits


NOW = "2026-08-30T01:00:00Z"


def _windows(reading: dict) -> list[tuple[str, str, float | None]]:
    return [
        (window["window_kind"], window["scope"], window["remaining_percent"])
        for window in reading["windows"]
    ]


def test_claude_parser_keeps_the_session_and_both_weekly_meters() -> None:
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
                    "scope": None,
                },
                {
                    "kind": "weekly_all",
                    "percent": 30,
                    "resets_at": "2026-09-04T01:00:00Z",
                    "scope": None,
                },
                {
                    "kind": "weekly_scoped",
                    "percent": 45,
                    "resets_at": "2026-09-04T01:00:00Z",
                    "scope": {"model": {"id": None, "display_name": "Fable"}},
                },
            ]
        },
        observed_at=NOW,
    )
    assert reading["plan_tier"] == "max"
    assert _windows(reading) == [
        ("rolling_5h", "all", 91.0),
        ("rolling_7d", "all", 70.0),
        ("rolling_7d", "Fable", 55.0),
    ]
    assert reading["windows"][0]["resets_at"] == "2026-08-30T03:00:00Z"


def test_claude_parser_names_no_scope_when_the_vendor_names_none() -> None:
    reading = parse_claude_usage(
        {},
        {"limits": [{"kind": "session", "percent": 9, "scope": {"surface": None}}]},
        observed_at=NOW,
    )
    assert _windows(reading) == [("rolling_5h", "all", 91.0)]


def test_codex_parser_keeps_every_bucket_and_both_windows() -> None:
    reading = parse_codex_rate_limits(
        {
            "rateLimits": {"planType": "pro"},
            "rateLimitsByLimitId": {
                "codex": {
                    "limitName": None,
                    "planType": "pro",
                    "primary": {
                        "usedPercent": 1,
                        "windowDurationMins": 10080,
                        "resetsAt": 1788643692,
                    },
                    "secondary": None,
                },
                "codex_bengalfox": {
                    "limitName": "GPT-5.3-Codex-Spark",
                    "planType": "pro",
                    "primary": {
                        "usedPercent": 4,
                        "windowDurationMins": 300,
                        "resetsAt": 1788643692,
                    },
                    "secondary": {
                        "usedPercent": 7,
                        "windowDurationMins": 10080,
                        "resetsAt": 1788643692,
                    },
                },
            },
        },
        observed_at=NOW,
    )
    assert reading["plan_tier"] == "pro"
    assert _windows(reading) == [
        ("rolling_7d", "all", 99.0),
        ("rolling_5h", "GPT-5.3-Codex-Spark", 96.0),
        ("rolling_7d", "GPT-5.3-Codex-Spark", 93.0),
    ]
    assert reading["windows"][0]["resets_at"] == "2026-09-05T21:28:12Z"


def test_codex_parser_reshapes_both_http_mirror_windows() -> None:
    reading = parse_codex_rate_limits(
        {
            "plan_type": "pro",
            "rate_limit": {
                "primary_window": {
                    "used_percent": 1,
                    "limit_window_seconds": 18000,
                    "reset_at": 1788643692,
                },
                "secondary_window": {
                    "used_percent": 11,
                    "limit_window_seconds": 604800,
                    "reset_at": 1788643692,
                },
            },
        },
        observed_at=NOW,
    )
    assert reading["plan_tier"] == "pro"
    assert _windows(reading) == [
        ("rolling_5h", "all", 99.0),
        ("rolling_7d", "all", 89.0),
    ]


def test_a_codex_payload_with_no_readable_window_is_named_unreadable() -> None:
    reading = parse_codex_rate_limits(
        {"rateLimits": {"planType": "pro"}}, observed_at=NOW
    )
    assert reading["plan_tier"] == "pro"
    assert _windows(reading) == [("unknown", "all", None)]
    assert reading["windows"][0]["reason"] == "usage_unreadable"


def test_cursor_parser_labels_the_monthly_billing_window() -> None:
    reading = parse_cursor_usage(
        {"planInfo": {"planName": "Ultra"}},
        {
            "billingCycleEnd": "1788742804000",
            "planUsage": {"totalPercentUsed": 70.94885714285715},
        },
        observed_at=NOW,
    )
    assert reading["plan_tier"] == "Ultra"
    window = reading["windows"][0]
    assert (window["window_kind"], window["scope"]) == ("monthly", "all")
    assert round(window["remaining_percent"], 2) == 29.05
    assert window["resets_at"] == "2026-09-07T01:00:04Z"


def test_sanitize_drops_token_bearing_keys() -> None:
    cleaned = sanitize_plan_limits(
        {
            "claude-cli": {
                "accessToken": "secret-token",
                "Authorization": "Bearer secret",
                "windows": [
                    {
                        "window_kind": "rolling_5h",
                        "scope": "all",
                        "remaining_percent": 80,
                        "status": "ok",
                        "accessToken": "secret-token",
                    }
                ],
            }
        }
    )
    assert "accessToken" not in cleaned["claude-cli"]
    assert "Authorization" not in str(cleaned)
    assert "secret-token" not in str(cleaned)


def test_a_reading_without_windows_names_the_relay_that_predates_them() -> None:
    """A relay on the old build must read as unreadable, never as blank."""
    cleaned = sanitize_plan_limits(
        {
            "claude-cli": {
                "surface": "claude-cli",
                "plan_tier": "max",
                "window_kind": "rolling_5h",
                "remaining_percent": 89.0,
                "status": "ok",
            }
        }
    )
    window = cleaned["claude-cli"]["windows"][0]
    assert window["status"] == "unknown"
    assert window["reason"] == RELAY_PREDATES_WINDOWS_REASON


def test_sanitize_bounds_how_many_windows_one_surface_can_publish() -> None:
    cleaned = sanitize_plan_limits(
        {
            "codex-cli": {
                "windows": [
                    {
                        "window_kind": "rolling_5h",
                        "scope": f"model-{index}",
                        "remaining_percent": 50,
                        "status": "ok",
                    }
                    for index in range(40)
                ]
            }
        }
    )
    assert len(cleaned["codex-cli"]["windows"]) == MAX_WINDOWS_PER_SURFACE


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

    assert readings["claude-cli"]["windows"][0]["reason"] == "probe_raised_RuntimeError"


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
    for readings in (first, second, third):
        assert readings["claude-cli"]["windows"][0]["reason"] == "stale_credential"


def test_a_cache_written_by_another_shape_is_discarded_not_reported(
    monkeypatch, tmp_path: Path
) -> None:
    """An upgraded relay re-probes rather than publishing unreadable rows."""
    calls: list[str] = []

    def _fake(surface: str, observed_at: str) -> dict:
        calls.append(surface)
        return unknown_reading(surface, "stale_credential", observed_at=observed_at)

    monkeypatch.setattr(limits, "_probe_one", _fake)
    limits._write_cache(
        {
            "schema_version": limits.PLAN_LIMIT_CACHE_SCHEMA_VERSION - 1,
            "probed_at": 1_000.0,
            "surfaces": {"claude-cli": {"status": "ok", "remaining_percent": 50}},
        },
        tmp_path,
    )

    readings = limits.observe_plan_limits(
        ("claude-cli",), state_dir=tmp_path, now=1_010.0, clock=lambda: NOW
    )

    assert calls == ["claude-cli"]
    assert readings["claude-cli"]["windows"][0]["reason"] == "stale_credential"
