"""Informational per-surface plan remaining for the steering fleet report."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from yoke_contracts.session_control.plan_limits import (
    ALL_MODELS_SCOPE,
    CLI_PLAN_LIMIT_SURFACES,
    sanitize_plan_limits,
)
from yoke_core.domain import db_backend


@dataclass(frozen=True)
class MachinePlanLimit:
    """One (machine, surface, window) meter as the report renders it."""

    machine_id: str
    #: The machine's registered name, which is what a person reading the report
    #: recognizes; a machine with no registry row falls back to its relay's
    #: reported host name.
    machine_name: str
    surface: str
    plan_tier: str | None
    window_kind: str
    scope: str
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
    from yoke_core.domain.machine_registry import display_name, machine_names

    names = machine_names(conn)
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
        machine_name = display_name(names, machine_id) or str(_cell(row, "hostname", 1))
        for surface in CLI_PLAN_LIMIT_SURFACES:
            row_data = remaining_source.get(surface)
            if row_data is None:
                continue
            plan_tier = row_data.get("plan_tier")
            for window in row_data.get("windows") or ():
                remaining = window.get("remaining_percent")
                found.append(
                    MachinePlanLimit(
                        machine_id=machine_id,
                        machine_name=machine_name,
                        surface=surface,
                        plan_tier=plan_tier if isinstance(plan_tier, str) else None,
                        window_kind=str(window.get("window_kind") or "unknown"),
                        scope=str(window.get("scope") or ALL_MODELS_SCOPE),
                        remaining_percent=float(remaining)
                        if isinstance(remaining, (int, float))
                        else None,
                        resets_at=window.get("resets_at")
                        if isinstance(window.get("resets_at"), str)
                        else None,
                        status=str(window.get("status") or "unknown"),
                        reason=window.get("reason")
                        if isinstance(window.get("reason"), str)
                        else None,
                    )
                )
    return tuple(found)


def fingerprint_material(limits: tuple[MachinePlanLimit, ...]) -> list[tuple[Any, ...]]:
    return sorted(
        (
            row.machine_id,
            row.surface,
            row.status,
            row.reason,
            row.window_kind,
            row.scope,
            row.remaining_percent,
            row.resets_at,
        )
        for row in limits
    )


__all__ = [
    "MachinePlanLimit",
    "fingerprint_material",
    "load_plan_limits",
]
