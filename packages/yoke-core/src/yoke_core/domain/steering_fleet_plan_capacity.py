"""Shared plan-capacity computer: raw readings plus window-normalized headroom.

The fleet-report table and any dashboard capacity view are two renderers of
this computer. One row per (machine, surface, window), because a vendor
publishes several meters at once and the operator needs to see the scoped
one that is about to bind as well as the account-wide one that is not.
Monthly remaining uses a 30-day window so percent is comparable across
surfaces; rolling windows use the same formula and understate true headroom
because they replenish continuously. Compare headroom across every surface
and window; under 100% is the only value that can hit a wall before reset.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from yoke_contracts.session_control.plan_limits import (
    ALL_MODELS_SCOPE,
    CURSOR_MODELS_SCOPE,
    CURSOR_OTHER_MODELS_SCOPE,
    cursor_scope_for_model,
)
from yoke_core.domain.steering_fleet_report_detectors import parse_stamp
from yoke_core.domain.steering_fleet_report_limits import MachinePlanLimit
from yoke_core.domain.steering_fleet_report_capacity import SessionCount
from yoke_core.domain.steering_fleet_report_balance import selection_labels


PLAN_LIMIT_HEADING = (
    "plan limits — informational remaining/reset; raise approaching walls "
    "with the operator, do not gate launches"
)
HEADROOM_LEGEND = (
    "headroom is remaining full-rate runway ÷ time-to-reset; ≥100% cannot "
    "exhaust before reset (informational, never gates launches). rolling "
    "windows understate because they replenish continuously. every window a "
    "surface publishes is listed; compare headroom across surfaces and "
    "windows — under 100% can hit a wall before its reset"
)
TABLE_HEADER = (
    "| Machine | Surface | Model / effort / context | Tier | Meter | Window | "
    "Quota left | Resets in | "
    "Headroom | Reset (UTC) |"
)
EMPTY = "-"
ROLLING_5H_WINDOW = timedelta(hours=5)
ROLLING_7D_WINDOW = timedelta(days=7)
MONTHLY_WINDOW = timedelta(days=30)
_WINDOW_BY_KIND = {
    "rolling_5h": ROLLING_5H_WINDOW,
    "rolling_7d": ROLLING_7D_WINDOW,
    "monthly": MONTHLY_WINDOW,
}
WINDOW_LABELS = {
    "rolling_5h": "rolling 5h",
    "rolling_7d": "weekly",
    "monthly": "monthly",
}
ALL_MODELS_LABEL = "all models"
# Shortest meter first, so a surface reads from the wall it hits soonest.
_WINDOW_ORDER = ("rolling_5h", "rolling_7d", "monthly")


def scope_label(scope: str) -> str:
    return ALL_MODELS_LABEL if scope == ALL_MODELS_SCOPE else scope


def window_label(window_kind: str, scope: str) -> str:
    """Name the meter and what it covers, e.g. ``weekly · Fable``.

    An unreadable window names no scope, because the reading that would
    have said what it covers is the thing that is missing.
    """
    kind = WINDOW_LABELS.get(window_kind, window_kind)
    if window_kind == "unknown":
        return kind
    return f"{kind} · {scope_label(scope)}"


@dataclass(frozen=True)
class PlanLimitComputation:
    machine_id: str
    machine_name: str
    surface: str
    plan_tier: str | None
    window_kind: str
    scope: str
    meter: str
    remaining_percent: float | None
    resets_at: str | None
    status: str
    reason: str | None
    window: timedelta | None
    remaining: timedelta | None
    until_reset: timedelta | None
    headroom_percent: float | None


def plan_window_length(window_kind: str) -> timedelta | None:
    return _WINDOW_BY_KIND.get(window_kind)


def remaining_capacity(
    remaining_percent: float | None, window: timedelta | None
) -> timedelta | None:
    if remaining_percent is None or window is None:
        return None
    return timedelta(seconds=window.total_seconds() * (remaining_percent / 100.0))


def time_until_reset(resets_at: str | None, now: str) -> timedelta | None:
    if not resets_at:
        return None
    try:
        return parse_stamp(resets_at) - parse_stamp(now)
    except (TypeError, ValueError):
        return None


def headroom_percent(
    remaining: timedelta | None, until_reset: timedelta | None
) -> float | None:
    if remaining is None or until_reset is None:
        return None
    seconds = until_reset.total_seconds()
    if seconds <= 0:
        return None
    return (remaining.total_seconds() / seconds) * 100.0


def format_capacity_duration(value: timedelta) -> str:
    """Minute-granularity duration, e.g. ``6d 14h 24m`` or ``5d 11h 40m``."""
    total_minutes = int(value.total_seconds() // 60)
    sign = "-" if total_minutes < 0 else ""
    total_minutes = abs(total_minutes)
    days, rem = divmod(total_minutes, 24 * 60)
    hours, minutes = divmod(rem, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    return sign + " ".join(parts)


def format_reset_utc(resets_at: str | None) -> str:
    if not resets_at:
        return EMPTY
    try:
        stamp = parse_stamp(resets_at)
    except (TypeError, ValueError):
        return EMPTY
    return f"{stamp.strftime('%b')} {stamp.day} {stamp.strftime('%H:%M')}"


def compute_plan_limit(row: MachinePlanLimit, *, now: str) -> PlanLimitComputation:
    """One surface's raw reading plus window-normalized headroom."""
    if row.status != "ok":
        return PlanLimitComputation(
            machine_id=row.machine_id,
            machine_name=row.machine_name,
            surface=row.surface,
            plan_tier=row.plan_tier,
            window_kind=row.window_kind,
            scope=row.scope,
            meter=row.meter,
            remaining_percent=row.remaining_percent,
            resets_at=row.resets_at,
            status=row.status,
            reason=row.reason,
            window=None,
            remaining=None,
            until_reset=None,
            headroom_percent=None,
        )
    window = plan_window_length(row.window_kind)
    remaining = remaining_capacity(row.remaining_percent, window)
    until_reset = time_until_reset(row.resets_at, now)
    return PlanLimitComputation(
        machine_id=row.machine_id,
        machine_name=row.machine_name,
        surface=row.surface,
        plan_tier=row.plan_tier,
        window_kind=row.window_kind,
        scope=row.scope,
        meter=row.meter,
        remaining_percent=row.remaining_percent,
        resets_at=row.resets_at,
        status=row.status,
        reason=row.reason,
        window=window,
        remaining=remaining,
        until_reset=until_reset,
        headroom_percent=headroom_percent(remaining, until_reset),
    )


def _dash(value: str | None) -> str:
    return value if value else EMPTY


def _percent(value: float | None) -> str:
    if value is None:
        return EMPTY
    return f"{int(round(value))}%"


def _selection_cell(
    computed: PlanLimitComputation,
    counts: tuple[SessionCount, ...],
) -> str:
    labels = selection_labels(
        _meter_counts(computed, counts),
        machine_id=computed.machine_id,
        surface=computed.surface,
    )
    return "<br>".join(labels) if labels else "no live selection"


def _meter_counts(
    row: MachinePlanLimit | PlanLimitComputation,
    counts: tuple[SessionCount, ...],
) -> tuple[SessionCount, ...]:
    if row.surface != "cursor-cli" or row.scope not in {
        CURSOR_MODELS_SCOPE,
        CURSOR_OTHER_MODELS_SCOPE,
    }:
        return counts
    return tuple(
        count
        for count in counts
        if cursor_scope_for_model(count.model or count.requested_model) == row.scope
    )


def _markdown_row(
    computed: PlanLimitComputation,
    counts: tuple[SessionCount, ...],
) -> str:
    selection = _selection_cell(computed, counts)
    if computed.status != "ok":
        return (
            f"| {computed.machine_name} | {computed.surface} | {selection} | "
            f"{EMPTY} | {_dash(computed.meter)} | "
            f"{window_label(computed.window_kind, computed.scope)} | "
            f"{EMPTY} | {EMPTY} | {computed.reason or 'unreadable'} | "
            f"{EMPTY} |"
        )
    resets_in = (
        format_capacity_duration(computed.until_reset)
        if computed.until_reset is not None
        else EMPTY
    )
    return (
        f"| {computed.machine_name} | {computed.surface} | {selection} | "
        f"{_dash(computed.plan_tier)} | "
        f"{_dash(computed.meter)} | "
        f"{window_label(computed.window_kind, computed.scope)} | "
        f"{_percent(computed.remaining_percent)} | {resets_in} | "
        f"{_percent(computed.headroom_percent)} | "
        f"{format_reset_utc(computed.resets_at)} |"
    )


def _sort_key(row: MachinePlanLimit) -> tuple[str, str, int, str, str, str]:
    try:
        order = _WINDOW_ORDER.index(row.window_kind)
    except ValueError:
        order = len(_WINDOW_ORDER)
    return (
        row.machine_name,
        row.surface,
        order,
        row.window_kind,
        row.scope,
        row.meter,
    )


def plan_limit_lines(
    limits: tuple[MachinePlanLimit, ...],
    *,
    now: str,
    session_counts: tuple[SessionCount, ...] = (),
) -> list[str]:
    if not limits:
        return []
    return [
        "",
        PLAN_LIMIT_HEADING + ":",
        TABLE_HEADER,
        *(
            _markdown_row(compute_plan_limit(row, now=now), session_counts)
            for row in sorted(limits, key=_sort_key)
        ),
        HEADROOM_LEGEND,
    ]


def plan_limit_dicts(
    limits: tuple[MachinePlanLimit, ...],
    *,
    now: str | None = None,
    session_counts: tuple[SessionCount, ...] = (),
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in limits:
        payload: dict[str, Any] = {
            "machine_id": row.machine_id,
            "machine_name": row.machine_name,
            "surface": row.surface,
            "plan_tier": row.plan_tier,
            "window_kind": row.window_kind,
            "scope": row.scope,
            "meter": row.meter,
            "window_label": window_label(row.window_kind, row.scope),
            "remaining_percent": row.remaining_percent,
            "resets_at": row.resets_at,
            "status": row.status,
            "reason": row.reason,
            "live_model_selections": list(
                selection_labels(
                    _meter_counts(row, session_counts),
                    machine_id=row.machine_id,
                    surface=row.surface,
                )
            ),
        }
        if now is not None:
            computed = compute_plan_limit(row, now=now)
            payload["window_seconds"] = (
                computed.window.total_seconds() if computed.window else None
            )
            payload["remaining_seconds"] = (
                computed.remaining.total_seconds() if computed.remaining else None
            )
            payload["until_reset_seconds"] = (
                computed.until_reset.total_seconds() if computed.until_reset else None
            )
            payload["headroom_percent"] = computed.headroom_percent
        rows.append(payload)
    return rows


__all__ = [
    "ALL_MODELS_LABEL",
    "EMPTY",
    "HEADROOM_LEGEND",
    "MONTHLY_WINDOW",
    "PLAN_LIMIT_HEADING",
    "PlanLimitComputation",
    "ROLLING_5H_WINDOW",
    "ROLLING_7D_WINDOW",
    "TABLE_HEADER",
    "WINDOW_LABELS",
    "compute_plan_limit",
    "format_capacity_duration",
    "format_reset_utc",
    "headroom_percent",
    "plan_limit_dicts",
    "plan_limit_lines",
    "plan_window_length",
    "remaining_capacity",
    "scope_label",
    "time_until_reset",
    "window_label",
]
