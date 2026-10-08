"""What each execution level can launch right now, and why.

For every level option this evaluates the quota pools that option's model
actually draws on, on every machine that can launch its surface, and says
whether it can launch, through which selection (a Cursor option falls back
only when its own pool is exhausted), and how much headroom it has. Then it
names where the next launch at that level would go:

- **Spread rule:** a surface above 100% headroom with no live worker gets the
  launch, so every harness with room stays exercised.
- **Most headroom** otherwise, across the option's own pools.
- Option order only breaks ties. A level with no launchable option has no
  capacity, and each option names the pool or machine gap that blocked it.

Exhaustion is affirmative only: an unreadable or unpublished meter never
blocks an option, it just leaves its headroom unknown. This module is pure;
:mod:`yoke_core.domain.universe_level_capacity_read` loads its inputs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional, Sequence

from yoke_contracts.levels import Level, LevelOption
from yoke_contracts.session_control.model_billing_pools import (
    pool_for_model,
    window_covers_model,
)
from yoke_contracts.session_control.plan_limits import (
    ALL_MODELS_SCOPE,
    CLI_PLAN_LIMIT_SURFACES,
)
from yoke_core.domain.steering_fleet_plan_capacity import WINDOW_LABELS, scope_label

#: Above this headroom a surface with no live worker takes the next launch.
SPREAD_HEADROOM_PERCENT = 100.0

SURFACE_VENDORS = {"claude-cli": "Claude", "codex-cli": "Codex", "cursor-cli": "Cursor"}


@dataclass(frozen=True)
class Meter:
    """One published quota window on one machine's surface."""

    machine_id: str
    surface: str
    window_kind: str
    scope: str
    status: str
    remaining_percent: Optional[float]
    headroom_percent: Optional[float]


def pool_label(surface: str, window_kind: str, scope: str, *, scoped: bool) -> str:
    """Name a pool the way an operator reads it, e.g. ``Claude weekly · Fable``.

    A vendor pool that is named by its scope (Cursor's two pools) reads by
    that name. Otherwise the vendor and window are named, and the scope is
    added only when the surface publishes more than one, because ``all
    models`` says nothing when no narrower pool sits beside it.
    """
    vendor = SURFACE_VENDORS.get(surface, surface)
    if scope != ALL_MODELS_SCOPE and pool_for_model(surface, scope) is not None:
        return scope if scope.startswith(vendor) else f"{vendor} {scope}"
    label = f"{vendor} {WINDOW_LABELS.get(window_kind, window_kind)}"
    return f"{label} · {scope_label(scope)}" if scoped else label


def _whole(value: Optional[float]) -> Optional[int]:
    return None if value is None else int(round(value))


@dataclass(frozen=True)
class _Reading:
    """One selection's standing on one machine."""

    machine_id: str
    pools: tuple[dict[str, Any], ...]
    blockers: tuple[dict[str, Any], ...]
    binding: Optional[dict[str, Any]]

    @property
    def headroom(self) -> Optional[int]:
        return self.binding["headroom"] if self.binding else None


def _rank(headroom: Optional[int]) -> float:
    return float("-inf") if headroom is None else float(headroom)


class _Fleet:
    def __init__(
        self, meters: Sequence[Meter], offered: Sequence[tuple[str, str]]
    ) -> None:
        self.by_machine: dict[tuple[str, str], list[Meter]] = {}
        for meter in meters:
            self.by_machine.setdefault((meter.machine_id, meter.surface), []).append(
                meter
            )
        self.offered = sorted(set(offered))

    def machines_for(self, surface: str) -> list[str]:
        return [machine for machine, offered in self.offered if offered == surface]

    def read(self, selection: LevelOption, machine_id: str) -> _Reading:
        windows = self.by_machine.get((machine_id, selection.surface), [])
        scoped = len({meter.scope for meter in windows}) > 1
        pools, blockers = [], []
        for meter in windows:
            if not window_covers_model(selection.surface, selection.model, meter.scope):
                continue
            readable = meter.status == "ok" and meter.remaining_percent is not None
            pool = {
                "label": pool_label(
                    selection.surface, meter.window_kind, meter.scope, scoped=scoped
                ),
                "left": _whole(meter.remaining_percent) if readable else None,
                "headroom": _whole(meter.headroom_percent) if readable else None,
            }
            pools.append(pool)
            if readable and meter.remaining_percent <= 0:
                blockers.append({"kind": "pool", "label": pool["label"], "left": 0})
        known = [pool for pool in pools if pool["headroom"] is not None]
        binding = min(known, key=lambda pool: pool["headroom"]) if known else None
        return _Reading(machine_id, tuple(pools), tuple(blockers), binding)

    def best(self, selection: LevelOption) -> Optional[_Reading]:
        """The machine reading this selection launches on, blocked or not."""
        readings = [
            self.read(selection, m) for m in self.machines_for(selection.surface)
        ]
        if not readings:
            return None
        open_readings = [r for r in readings if not r.blockers]
        pick_from = open_readings or readings
        return max(pick_from, key=lambda r: _rank(r.headroom))


def _option_payload(
    option: LevelOption, reading: Optional[_Reading], display: Callable[[str], str]
) -> dict[str, Any]:
    return {
        "surface": option.surface,
        "model": option.model,
        "display_name": display(option.model),
        "native_selector": option.surface == "cursor-cli",
        "reasoning_effort": option.reasoning_effort,
        "context_window_tokens": option.context_window_tokens,
        "pools": list(reading.pools) if reading else [],
    }


def _no_machine(surface: str) -> dict[str, Any]:
    return {"kind": "no_machine", "surface": surface}


def _evaluate_option(
    option: LevelOption, fleet: _Fleet, display: Callable[[str], str]
) -> dict[str, Any]:
    primary = fleet.best(option)
    payload = _option_payload(option, primary, display)
    blockers = list(primary.blockers) if primary else [_no_machine(option.surface)]
    selected: Optional[tuple[LevelOption, _Reading]] = None
    if primary is not None and not primary.blockers:
        selected = (option, primary)
    if option.fallback is not None:
        fallback = fleet.best(option.fallback)
        payload["fallback"] = _option_payload(option.fallback, fallback, display)
        if selected is None and fallback is not None:
            if fallback.blockers:
                blockers.extend(fallback.blockers)
            else:
                selected = (option.fallback, fallback)
    if selected is None:
        payload["now"] = {"state": "blocked", "blockers": blockers}
        return payload
    selection, reading = selected
    payload["now"] = {
        "state": "can_launch",
        "via": None if selection is option else selection.model,
        "via_display_name": None if selection is option else display(selection.model),
        "machine_id": reading.machine_id,
        "binding_pool": reading.binding,
    }
    return payload


def _next_launch(
    options: Sequence[dict[str, Any]], live_workers: Mapping[str, int]
) -> Optional[dict[str, Any]]:
    candidates = [
        (index, option)
        for index, option in enumerate(options)
        if option["now"]["state"] == "can_launch"
    ]
    if not candidates:
        return None

    def headroom(candidate: tuple[int, dict[str, Any]]) -> Optional[int]:
        pool = candidate[1]["now"]["binding_pool"]
        return pool["headroom"] if pool else None

    def best(pool: list[tuple[int, dict[str, Any]]]) -> tuple[int, dict[str, Any]]:
        # max() keeps the first of equals, so option order breaks ties.
        return max(pool, key=lambda candidate: _rank(headroom(candidate)))

    spread = [
        c
        for c in candidates
        if (headroom(c) or 0) > SPREAD_HEADROOM_PERCENT
        and not live_workers.get(c[1]["surface"])
    ]
    if spread:
        index, option = best(spread)
        reason = (
            f"spread rule: no live worker on {option['surface']}, "
            f"{headroom((index, option))}% headroom"
        )
    else:
        index, option = best(candidates)
        pool = option["now"]["binding_pool"]
        reason = (
            f"most headroom: {pool['headroom']}% on {pool['label']}"
            if pool
            else "option order: no option publishes a readable headroom"
        )
    now = option["now"]
    return {
        "option_index": index,
        "surface": option["surface"],
        "model": now["via"] or option["model"],
        "display_name": now["via_display_name"] or option["display_name"],
        "reason": reason,
    }


def evaluate_level_capacity(
    levels: Sequence[Level],
    *,
    meters: Sequence[Meter],
    offered: Sequence[tuple[str, str]],
    live_workers: Mapping[str, int],
    display: Callable[[str], str],
) -> list[dict[str, Any]]:
    """Each level with its options' launch standing and its next launch."""
    fleet = _Fleet(meters, offered)
    out: list[dict[str, Any]] = []
    for level in levels:
        options = [_evaluate_option(option, fleet, display) for option in level.options]
        out.append(
            {
                "name": level.name,
                "glyph": level.glyph,
                "launchable_surfaces": [
                    surface
                    for surface in CLI_PLAN_LIMIT_SURFACES
                    if any(
                        o["surface"] == surface and o["now"]["state"] == "can_launch"
                        for o in options
                    )
                ],
                "next_launch": _next_launch(options, live_workers),
                "options": options,
            }
        )
    return out


__all__ = [
    "Meter",
    "SPREAD_HEADROOM_PERCENT",
    "SURFACE_VENDORS",
    "evaluate_level_capacity",
    "pool_label",
]
