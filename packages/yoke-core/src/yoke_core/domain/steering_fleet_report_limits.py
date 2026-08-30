"""Informational per-surface plan remaining for the steering fleet report."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from yoke_contracts.session_control.plan_limits import (
    CLI_PLAN_LIMIT_SURFACES,
    sanitize_plan_limits,
)
from yoke_core.domain import db_backend


PLAN_LIMIT_HEADING = (
    "plan limits — informational remaining/reset; raise approaching walls "
    "with the operator, do not gate launches"
)


@dataclass(frozen=True)
class MachinePlanLimit:
    machine_id: str
    hostname: str
    surface: str
    plan_tier: str | None
    window_kind: str
    remaining_percent: float | None
    resets_at: str | None
    status: str
    reason: str | None


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _document(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value or ""))
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _projects(value: Any) -> set[int]:
    if isinstance(value, list):
        raw = value
    else:
        try:
            raw = json.loads(str(value or "[]"))
        except (TypeError, ValueError):
            return set()
    out: set[int] = set()
    if not isinstance(raw, list):
        return out
    for item in raw:
        try:
            out.add(int(item))
        except (TypeError, ValueError):
            continue
    return out


def _cell(row: Any, key: str, index: int) -> Any:
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return row[index]


def load_plan_limits(
    conn: Any, *, project_id: int, now: str
) -> tuple[MachinePlanLimit, ...]:
    """Connected relays' cached readings for machines serving this project."""
    marker = _p(conn)
    rows = conn.execute(
        "SELECT machine_id, hostname, project_checkouts, surface_plan_limits "
        f"FROM session_relays WHERE connected_until>={marker} "
        "ORDER BY hostname, machine_id",
        (now,),
    ).fetchall()
    found: list[MachinePlanLimit] = []
    for row in rows:
        if int(project_id) not in _projects(_cell(row, "project_checkouts", 2)):
            continue
        remaining_source = sanitize_plan_limits(
            _document(_cell(row, "surface_plan_limits", 3))
        )
        machine_id = str(_cell(row, "machine_id", 0))
        hostname = str(_cell(row, "hostname", 1))
        for surface in CLI_PLAN_LIMIT_SURFACES:
            row_data = remaining_source.get(surface)
            if row_data is None:
                continue
            remaining = row_data.get("remaining_percent")
            found.append(
                MachinePlanLimit(
                    machine_id=machine_id,
                    hostname=hostname,
                    surface=surface,
                    plan_tier=row_data.get("plan_tier")
                    if isinstance(row_data.get("plan_tier"), str)
                    else None,
                    window_kind=str(row_data.get("window_kind") or "unknown"),
                    remaining_percent=float(remaining)
                    if isinstance(remaining, (int, float))
                    else None,
                    resets_at=row_data.get("resets_at")
                    if isinstance(row_data.get("resets_at"), str)
                    else None,
                    status=str(row_data.get("status") or "unknown"),
                    reason=row_data.get("reason")
                    if isinstance(row_data.get("reason"), str)
                    else None,
                )
            )
    return tuple(found)


def plan_limit_lines(limits: tuple[MachinePlanLimit, ...]) -> list[str]:
    if not limits:
        return []
    by_machine: dict[str, list[MachinePlanLimit]] = {}
    for row in limits:
        by_machine.setdefault(row.machine_id, []).append(row)
    lines = ["", PLAN_LIMIT_HEADING + ":"]
    for machine in sorted(by_machine):
        lines.append(f"  {machine}")
        for row in sorted(by_machine[machine], key=lambda item: item.surface):
            if row.status != "ok":
                lines.append(
                    f"    {row.surface}  unknown  {row.reason or 'unreadable'}"
                )
                continue
            remaining = (
                f"{int(round(row.remaining_percent))}%"
                if row.remaining_percent is not None
                else "?"
            )
            tier = row.plan_tier or "unspecified"
            reset = row.resets_at or "unknown-reset"
            lines.append(
                f"    {row.surface}  {tier}  {remaining} remaining  "
                f"{row.window_kind}  resets {reset}"
            )
    return lines


def plan_limit_dicts(limits: tuple[MachinePlanLimit, ...]) -> list[dict[str, Any]]:
    return [
        {
            "machine_id": row.machine_id,
            "hostname": row.hostname,
            "surface": row.surface,
            "plan_tier": row.plan_tier,
            "window_kind": row.window_kind,
            "remaining_percent": row.remaining_percent,
            "resets_at": row.resets_at,
            "status": row.status,
            "reason": row.reason,
        }
        for row in limits
    ]


def fingerprint_material(limits: tuple[MachinePlanLimit, ...]) -> list[tuple[Any, ...]]:
    return sorted(
        (
            row.machine_id,
            row.surface,
            row.status,
            row.reason,
            row.window_kind,
            row.remaining_percent,
            row.resets_at,
        )
        for row in limits
    )


__all__ = [
    "PLAN_LIMIT_HEADING",
    "MachinePlanLimit",
    "fingerprint_material",
    "load_plan_limits",
    "plan_limit_dicts",
    "plan_limit_lines",
]
