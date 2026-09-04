"""Vendor usage payloads to normalized plan-limit windows.

One parser per CLI surface. Each keeps every meter the vendor publishes,
naming the model scope each meter covers, and reports an unreadable surface
rather than an empty one.
"""

from __future__ import annotations

from typing import Any, Mapping

from yoke_contracts.session_control.plan_limits import (
    ALL_MODELS_SCOPE,
    CURSOR_MODELS_SCOPE,
    CURSOR_OTHER_MODELS_SCOPE,
    iso_from_epoch_ms,
    iso_from_epoch_seconds,
    plan_limit_window,
    remaining_from_used_percent,
    surface_reading,
    unknown_reading,
)

_UNREADABLE = "usage_unreadable"


def _kind_from_minutes(minutes: object) -> str:
    try:
        value = int(minutes)
    except (TypeError, ValueError):
        return "unknown"
    if value == 300:
        return "rolling_5h"
    if value == 10080:
        return "rolling_7d"
    return "unknown"


def _kind_from_claude(kind: object) -> str:
    token = str(kind or "")
    if token in {"session", "five_hour"}:
        return "rolling_5h"
    if token in {"weekly_all", "weekly_scoped", "seven_day"}:
        return "rolling_7d"
    return "unknown"


def _claude_scope(scope: object) -> str:
    """Claude names a scoped meter's model family under ``scope.model``."""
    if not isinstance(scope, Mapping):
        return ALL_MODELS_SCOPE
    model = scope.get("model")
    if not isinstance(model, Mapping):
        return ALL_MODELS_SCOPE
    name = model.get("display_name") or model.get("id")
    return str(name) if name else ALL_MODELS_SCOPE


def parse_claude_usage(
    credentials: Mapping[str, Any],
    usage: Mapping[str, Any],
    *,
    observed_at: str,
) -> dict[str, Any]:
    oauth = credentials.get("claudeAiOauth")
    oauth = oauth if isinstance(oauth, Mapping) else credentials
    plan_tier = oauth.get("subscriptionType") if isinstance(oauth, Mapping) else None
    plan_tier = str(plan_tier) if plan_tier else None
    windows: list[dict[str, Any]] = []
    for row in usage.get("limits") or []:
        if not isinstance(row, Mapping):
            continue
        remaining = remaining_from_used_percent(row.get("percent"))
        if remaining is None:
            continue
        resets = row.get("resets_at")
        windows.append(
            plan_limit_window(
                window_kind=_kind_from_claude(row.get("kind")),
                scope=_claude_scope(row.get("scope")),
                meter=f"oauth_usage.limits.{row.get('kind') or 'unknown'}",
                remaining_percent=remaining,
                resets_at=str(resets) if resets else None,
            )
        )
    if not windows:
        return unknown_reading(
            "claude-cli", _UNREADABLE, observed_at=observed_at, plan_tier=plan_tier
        )
    return surface_reading(
        "claude-cli", observed_at=observed_at, plan_tier=plan_tier, windows=windows
    )


def _codex_from_http_mirror(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    """Reshape the HTTP usage mirror into the app-server bucket shape."""
    rate_limit = payload.get("rate_limit")
    if not isinstance(rate_limit, Mapping):
        return payload
    snapshot: dict[str, Any] = {
        "planType": payload.get("plan_type"),
        "limitName": None,
    }
    for source, target in (
        ("primary_window", "primary"),
        ("secondary_window", "secondary"),
    ):
        window = rate_limit.get(source)
        if not isinstance(window, Mapping):
            continue
        try:
            minutes: int | None = int(window["limit_window_seconds"]) // 60
        except (TypeError, ValueError, KeyError):
            minutes = None
        snapshot[target] = {
            "usedPercent": window.get("used_percent"),
            "windowDurationMins": minutes,
            "resetsAt": window.get("reset_at"),
        }
    if "primary" not in snapshot and "secondary" not in snapshot:
        return payload
    return {"rateLimits": snapshot, "rateLimitsByLimitId": {"codex": snapshot}}


def _codex_scope(bucket: Mapping[str, Any]) -> str:
    """Codex names a model-family bucket; the account-wide bucket is unnamed."""
    name = bucket.get("limitName")
    return str(name) if isinstance(name, str) and name.strip() else ALL_MODELS_SCOPE


def _codex_resets_at(value: object) -> str | None:
    if value is None:
        return None
    try:
        return iso_from_epoch_seconds(float(value))
    except (TypeError, ValueError):
        return None


def parse_codex_rate_limits(
    payload: Mapping[str, Any], *, observed_at: str
) -> dict[str, Any]:
    if "rateLimits" not in payload and "rate_limit" in payload:
        payload = _codex_from_http_mirror(payload)
    buckets = payload.get("rateLimitsByLimitId")
    if not isinstance(buckets, Mapping) or not buckets:
        snapshot = payload.get("rateLimits")
        buckets = {"codex": snapshot} if isinstance(snapshot, Mapping) else {}
    plan_tier: str | None = None
    windows: list[dict[str, Any]] = []
    for limit_id in sorted(buckets):
        bucket = buckets[limit_id]
        if not isinstance(bucket, Mapping):
            continue
        if plan_tier is None and bucket.get("planType"):
            plan_tier = str(bucket["planType"])
        scope = _codex_scope(bucket)
        for key in ("primary", "secondary"):
            window = bucket.get(key)
            if not isinstance(window, Mapping):
                continue
            remaining = remaining_from_used_percent(window.get("usedPercent"))
            if remaining is None:
                continue
            windows.append(
                plan_limit_window(
                    window_kind=_kind_from_minutes(window.get("windowDurationMins")),
                    scope=scope,
                    meter=f"rateLimitsByLimitId.{limit_id}.{key}",
                    remaining_percent=remaining,
                    resets_at=_codex_resets_at(window.get("resetsAt")),
                )
            )
    if not windows:
        return unknown_reading(
            "codex-cli", _UNREADABLE, observed_at=observed_at, plan_tier=plan_tier
        )
    return surface_reading(
        "codex-cli", observed_at=observed_at, plan_tier=plan_tier, windows=windows
    )


def parse_cursor_usage(
    plan: Mapping[str, Any],
    usage: Mapping[str, Any],
    *,
    observed_at: str,
) -> dict[str, Any]:
    """Read the two included-usage pools that Cursor bills by model family."""
    info = plan.get("planInfo") if isinstance(plan.get("planInfo"), Mapping) else plan
    plan_tier = info.get("planName") if isinstance(info, Mapping) else None
    plan_tier = str(plan_tier) if plan_tier else None
    spend = usage.get("planUsage")
    windows: list[dict[str, Any]] = []
    for field, scope in (
        ("autoPercentUsed", CURSOR_MODELS_SCOPE),
        ("apiPercentUsed", CURSOR_OTHER_MODELS_SCOPE),
    ):
        remaining = (
            remaining_from_used_percent(spend.get(field))
            if isinstance(spend, Mapping)
            else None
        )
        if remaining is None:
            continue
        windows.append(
            plan_limit_window(
                window_kind="monthly",
                scope=scope,
                meter=f"planUsage.{field}",
                remaining_percent=remaining,
                resets_at=iso_from_epoch_ms(usage.get("billingCycleEnd")),
            )
        )
    if not windows:
        return unknown_reading(
            "cursor-cli", _UNREADABLE, observed_at=observed_at, plan_tier=plan_tier
        )
    return surface_reading(
        "cursor-cli",
        observed_at=observed_at,
        plan_tier=plan_tier,
        windows=windows,
    )


__all__ = [
    "parse_claude_usage",
    "parse_codex_rate_limits",
    "parse_cursor_usage",
]
