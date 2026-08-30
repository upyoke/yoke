"""Normalized per-surface plan-limit readings. Values only; never tokens."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

CLI_PLAN_LIMIT_SURFACES = ("claude-cli", "codex-cli", "cursor-cli")
PLAN_LIMIT_STATUSES = frozenset({"ok", "unknown"})
PLAN_LIMIT_WINDOW_KINDS = frozenset({"rolling_5h", "rolling_7d", "monthly", "unknown"})
_READING_KEYS = (
    "surface",
    "plan_tier",
    "window_kind",
    "remaining_percent",
    "resets_at",
    "status",
    "reason",
    "observed_at",
)
_STRING_MAX = 128


def iso_from_epoch_seconds(seconds: float) -> str:
    return datetime.fromtimestamp(float(seconds), timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def iso_from_epoch_ms(value: object) -> str | None:
    try:
        return iso_from_epoch_seconds(float(str(value)) / 1000.0)
    except (TypeError, ValueError):
        return None


def unknown_reading(
    surface: str, reason: str, *, observed_at: str, plan_tier: str | None = None
) -> dict[str, Any]:
    return {
        "surface": surface,
        "plan_tier": plan_tier,
        "window_kind": "unknown",
        "remaining_percent": None,
        "resets_at": None,
        "status": "unknown",
        "reason": reason,
        "observed_at": observed_at,
    }


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


def _remaining(used: object) -> float | None:
    try:
        percent = 100.0 - float(used)
    except (TypeError, ValueError):
        return None
    if percent < 0 or percent > 100:
        return None
    return percent


def _pick_tightest(
    candidates: list[tuple[float, str, str | None]],
) -> tuple[float, str, str | None] | None:
    if not candidates:
        return None
    return min(candidates, key=lambda row: row[0])


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
    candidates: list[tuple[float, str, str | None]] = []
    for row in usage.get("limits") or []:
        if not isinstance(row, Mapping):
            continue
        remaining = _remaining(row.get("percent"))
        if remaining is None:
            continue
        resets = row.get("resets_at")
        candidates.append(
            (
                remaining,
                _kind_from_claude(row.get("kind")),
                str(resets) if resets else None,
            )
        )
    picked = _pick_tightest(candidates)
    if picked is None:
        return unknown_reading(
            "claude-cli",
            "usage_unreadable",
            observed_at=observed_at,
            plan_tier=plan_tier,
        )
    remaining, window_kind, resets_at = picked
    return {
        "surface": "claude-cli",
        "plan_tier": plan_tier,
        "window_kind": window_kind,
        "remaining_percent": remaining,
        "resets_at": resets_at,
        "status": "ok",
        "reason": None,
        "observed_at": observed_at,
    }


def _codex_from_http_mirror(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    window = payload.get("rate_limit")
    window = window.get("primary_window") if isinstance(window, Mapping) else None
    if not isinstance(window, Mapping):
        return payload
    try:
        minutes = int(window["limit_window_seconds"]) // 60
    except (TypeError, ValueError, KeyError):
        minutes = None
    snapshot = {
        "planType": payload.get("plan_type"),
        "primary": {
            "usedPercent": window.get("used_percent"),
            "windowDurationMins": minutes,
            "resetsAt": window.get("reset_at"),
        },
    }
    return {"rateLimits": snapshot, "rateLimitsByLimitId": {"codex": snapshot}}


def parse_codex_rate_limits(
    payload: Mapping[str, Any], *, observed_at: str
) -> dict[str, Any]:
    if "rateLimits" not in payload and "rate_limit" in payload:
        payload = _codex_from_http_mirror(payload)
    buckets = payload.get("rateLimitsByLimitId")
    if not isinstance(buckets, Mapping):
        buckets = {}
    snapshot = buckets.get("codex")
    if not isinstance(snapshot, Mapping):
        snapshot = payload.get("rateLimits")
    if not isinstance(snapshot, Mapping):
        return unknown_reading("codex-cli", "usage_unreadable", observed_at=observed_at)
    primary = snapshot.get("primary")
    if not isinstance(primary, Mapping):
        return unknown_reading(
            "codex-cli",
            "usage_unreadable",
            observed_at=observed_at,
            plan_tier=str(snapshot["planType"]) if snapshot.get("planType") else None,
        )
    remaining = _remaining(primary.get("usedPercent"))
    resets = primary.get("resetsAt")
    try:
        resets_at = (
            iso_from_epoch_seconds(float(resets)) if resets is not None else None
        )
    except (TypeError, ValueError):
        resets_at = None
    plan_tier = str(snapshot["planType"]) if snapshot.get("planType") else None
    if remaining is None:
        return unknown_reading(
            "codex-cli",
            "usage_unreadable",
            observed_at=observed_at,
            plan_tier=plan_tier,
        )
    return {
        "surface": "codex-cli",
        "plan_tier": plan_tier,
        "window_kind": _kind_from_minutes(primary.get("windowDurationMins")),
        "remaining_percent": remaining,
        "resets_at": resets_at,
        "status": "ok",
        "reason": None,
        "observed_at": observed_at,
    }


def parse_cursor_usage(
    plan: Mapping[str, Any],
    usage: Mapping[str, Any],
    *,
    observed_at: str,
) -> dict[str, Any]:
    info = plan.get("planInfo") if isinstance(plan.get("planInfo"), Mapping) else plan
    plan_tier = info.get("planName") if isinstance(info, Mapping) else None
    plan_tier = str(plan_tier) if plan_tier else None
    spend = usage.get("planUsage")
    if not isinstance(spend, Mapping):
        return unknown_reading(
            "cursor-cli",
            "usage_unreadable",
            observed_at=observed_at,
            plan_tier=plan_tier,
        )
    remaining = _remaining(spend.get("totalPercentUsed"))
    if remaining is None:
        return unknown_reading(
            "cursor-cli",
            "usage_unreadable",
            observed_at=observed_at,
            plan_tier=plan_tier,
        )
    return {
        "surface": "cursor-cli",
        "plan_tier": plan_tier,
        "window_kind": "monthly",
        "remaining_percent": remaining,
        "resets_at": iso_from_epoch_ms(usage.get("billingCycleEnd")),
        "status": "ok",
        "reason": None,
        "observed_at": observed_at,
    }


def _clip(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:_STRING_MAX]


def sanitize_plan_limits(raw: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Allowlisted values-only rows. Extra keys, including tokens, are dropped."""
    cleaned: dict[str, dict[str, Any]] = {}
    if not isinstance(raw, Mapping):
        return cleaned
    for surface in CLI_PLAN_LIMIT_SURFACES:
        row = raw.get(surface)
        if not isinstance(row, Mapping):
            continue
        status = str(row.get("status") or "unknown")
        if status not in PLAN_LIMIT_STATUSES:
            status = "unknown"
        window_kind = str(row.get("window_kind") or "unknown")
        if window_kind not in PLAN_LIMIT_WINDOW_KINDS:
            window_kind = "unknown"
        remaining = row.get("remaining_percent")
        try:
            remaining_percent = float(remaining) if remaining is not None else None
        except (TypeError, ValueError):
            remaining_percent = None
        if remaining_percent is not None and (
            remaining_percent < 0 or remaining_percent > 100
        ):
            remaining_percent = None
            status = "unknown"
        cleaned[surface] = {
            "surface": surface,
            "plan_tier": _clip(row.get("plan_tier")),
            "window_kind": window_kind,
            "remaining_percent": remaining_percent,
            "resets_at": _clip(row.get("resets_at")),
            "status": status,
            "reason": _clip(row.get("reason")),
            "observed_at": _clip(row.get("observed_at")) or "",
        }
        for key in list(cleaned[surface]):
            if key not in _READING_KEYS:
                del cleaned[surface][key]
    return cleaned


__all__ = [
    "CLI_PLAN_LIMIT_SURFACES",
    "PLAN_LIMIT_STATUSES",
    "PLAN_LIMIT_WINDOW_KINDS",
    "iso_from_epoch_ms",
    "iso_from_epoch_seconds",
    "parse_claude_usage",
    "parse_codex_rate_limits",
    "parse_cursor_usage",
    "sanitize_plan_limits",
    "unknown_reading",
]
