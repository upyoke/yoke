"""Normalized per-surface plan-limit readings. Values only; never tokens.

A surface reading carries EVERY usage window its vendor exposes, because a
vendor publishes several meters at once and only one of them binds. Claude
publishes a rolling five-hour session meter plus two weekly meters — one for
all models and one scoped to a named model family; Codex publishes a primary
and a secondary window per limit bucket, and one bucket per model family;
Cursor publishes separate monthly included-usage pools for Cursor Models and
Other Models. Collapsing those to one blended percentage hides the pool a
requested model actually draws from.

Status and reason live on the window rather than the surface, so a surface
that could not be read is one window that names its own refusal. That also
makes the shape self-announcing to a reader that predates it: a build looking
for a surface-level ``status`` finds none, reads ``unknown``, and renders a
labelled unreadable row instead of a blank one.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

CLI_PLAN_LIMIT_SURFACES = ("claude-cli", "codex-cli", "cursor-cli")
PLAN_LIMIT_STATUSES = frozenset({"ok", "unknown"})
PLAN_LIMIT_WINDOW_KINDS = frozenset({"rolling_5h", "rolling_7d", "monthly", "unknown"})

# The scope sentinel for a meter that covers every model, as opposed to one
# named for a model family ("Fable", "GPT-5.3-Codex-Spark").
ALL_MODELS_SCOPE = "all"
CURSOR_MODELS_SCOPE = "Cursor Models"
CURSOR_OTHER_MODELS_SCOPE = "Other Models"
CURSOR_MODELS_PREFIXES = ("cursor-grok-", "composer-")

# A vendor that starts publishing a bucket per model must not be able to grow
# one machine row without bound.
MAX_WINDOWS_PER_SURFACE = 16

# A heartbeat with no windows list at all comes from a relay running a build
# that predates per-window readings; updating that machine's relay is the
# fix. A list that yields no usable window is a malformed document instead,
# and the two must not share a name.
RELAY_PREDATES_WINDOWS_REASON = "relay_predates_window_readings"
WINDOWS_UNREADABLE_REASON = "plan_limit_windows_unreadable"

_WINDOW_KEYS = (
    "window_kind",
    "scope",
    "meter",
    "remaining_percent",
    "resets_at",
    "status",
    "reason",
)
_READING_KEYS = ("surface", "plan_tier", "observed_at", "windows")
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


def remaining_from_used_percent(used: object) -> float | None:
    try:
        percent = 100.0 - float(used)
    except (TypeError, ValueError):
        return None
    if percent < 0 or percent > 100:
        return None
    return percent


def plan_limit_window(
    *,
    window_kind: str,
    scope: str,
    meter: str,
    remaining_percent: float,
    resets_at: str | None,
) -> dict[str, Any]:
    """One readable meter: its kind, what it covers, and what is left."""
    return {
        "window_kind": window_kind,
        "scope": scope,
        "meter": meter,
        "remaining_percent": remaining_percent,
        "resets_at": resets_at,
        "status": "ok",
        "reason": None,
    }


def unknown_window(reason: str) -> dict[str, Any]:
    return {
        "window_kind": "unknown",
        "scope": ALL_MODELS_SCOPE,
        "meter": "unknown",
        "remaining_percent": None,
        "resets_at": None,
        "status": "unknown",
        "reason": reason,
    }


def surface_reading(
    surface: str,
    *,
    observed_at: str,
    plan_tier: str | None,
    windows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "surface": surface,
        "plan_tier": plan_tier,
        "observed_at": observed_at,
        "windows": [dict(window) for window in windows],
    }


def unknown_reading(
    surface: str, reason: str, *, observed_at: str, plan_tier: str | None = None
) -> dict[str, Any]:
    """A surface that could not be read: one window carrying the refusal."""
    return surface_reading(
        surface,
        observed_at=observed_at,
        plan_tier=plan_tier,
        windows=(unknown_window(reason),),
    )


def reading_is_ok(reading: Mapping[str, Any]) -> bool:
    """True when at least one window of this surface was actually read."""
    windows = reading.get("windows")
    if not isinstance(windows, Sequence) or isinstance(windows, (str, bytes)):
        return False
    return any(
        isinstance(window, Mapping) and window.get("status") == "ok"
        for window in windows
    )


def _clip(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:_STRING_MAX]


def _sanitize_window(raw: Mapping[str, Any]) -> dict[str, Any]:
    status = str(raw.get("status") or "unknown")
    if status not in PLAN_LIMIT_STATUSES:
        status = "unknown"
    window_kind = str(raw.get("window_kind") or "unknown")
    if window_kind not in PLAN_LIMIT_WINDOW_KINDS:
        window_kind = "unknown"
    remaining = raw.get("remaining_percent")
    try:
        remaining_percent = float(remaining) if remaining is not None else None
    except (TypeError, ValueError):
        remaining_percent = None
    if remaining_percent is not None and (
        remaining_percent < 0 or remaining_percent > 100
    ):
        remaining_percent = None
        status = "unknown"
    return {
        "window_kind": window_kind,
        "scope": _clip(raw.get("scope")) or ALL_MODELS_SCOPE,
        "meter": _clip(raw.get("meter")) or "unknown",
        "remaining_percent": remaining_percent,
        "resets_at": _clip(raw.get("resets_at")),
        "status": status,
        "reason": _clip(raw.get("reason")),
    }


def cursor_scope_for_model(model: object) -> str:
    """Resolve Cursor's billed pool with the provider's model-prefix rule."""
    value = str(model or "").strip().lower()
    if any(value.startswith(prefix) for prefix in CURSOR_MODELS_PREFIXES):
        return CURSOR_MODELS_SCOPE
    return CURSOR_OTHER_MODELS_SCOPE


def _sanitize_windows(raw: Any) -> list[dict[str, Any]]:
    if raw is None:
        return [unknown_window(RELAY_PREDATES_WINDOWS_REASON)]
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return [unknown_window(WINDOWS_UNREADABLE_REASON)]
    windows = [
        _sanitize_window(window)
        for window in raw[:MAX_WINDOWS_PER_SURFACE]
        if isinstance(window, Mapping)
    ]
    return windows or [unknown_window(WINDOWS_UNREADABLE_REASON)]


def sanitize_plan_limits(raw: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Allowlisted values-only rows. Extra keys, including tokens, are dropped."""
    cleaned: dict[str, dict[str, Any]] = {}
    if not isinstance(raw, Mapping):
        return cleaned
    for surface in CLI_PLAN_LIMIT_SURFACES:
        row = raw.get(surface)
        if not isinstance(row, Mapping):
            continue
        entry = {
            "surface": surface,
            "plan_tier": _clip(row.get("plan_tier")),
            "observed_at": _clip(row.get("observed_at")) or "",
            "windows": _sanitize_windows(row.get("windows")),
        }
        cleaned[surface] = {key: entry[key] for key in _READING_KEYS}
        for window in cleaned[surface]["windows"]:
            for key in list(window):
                if key not in _WINDOW_KEYS:
                    del window[key]
    return cleaned


__all__ = [
    "ALL_MODELS_SCOPE",
    "CLI_PLAN_LIMIT_SURFACES",
    "CURSOR_MODELS_PREFIXES",
    "CURSOR_MODELS_SCOPE",
    "CURSOR_OTHER_MODELS_SCOPE",
    "MAX_WINDOWS_PER_SURFACE",
    "PLAN_LIMIT_STATUSES",
    "PLAN_LIMIT_WINDOW_KINDS",
    "RELAY_PREDATES_WINDOWS_REASON",
    "WINDOWS_UNREADABLE_REASON",
    "cursor_scope_for_model",
    "iso_from_epoch_ms",
    "iso_from_epoch_seconds",
    "plan_limit_window",
    "reading_is_ok",
    "remaining_from_used_percent",
    "sanitize_plan_limits",
    "surface_reading",
    "unknown_reading",
    "unknown_window",
]
