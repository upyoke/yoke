"""Model/minimum-effort rows with capacity from observed native selections."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional, Sequence

from yoke_contracts.levels import Level
from yoke_core.domain.level_native_selections import (
    NativeLevelSelection,
    native_selections,
)
from yoke_contracts.session_control.model_billing_pools import (
    pool_for_model,
    window_covers_model,
)
from yoke_contracts.session_control.plan_limits import (
    ALL_MODELS_SCOPE,
    CLI_PLAN_LIMIT_SURFACES,
)
from yoke_core.domain.steering_fleet_plan_capacity import WINDOW_LABELS, scope_label

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
    #: Whether an empty included window really stops work: fresh paid extra
    #: usage is disabled, capped or unfunded. Unknown or stale never blocks.
    extra_blocks: bool = False
    #: The shared phrase naming the surface's extra-usage facts.
    extra: str = ""


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

    def read(self, selection: NativeLevelSelection, machine_id: str) -> _Reading:
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
            if readable and meter.remaining_percent <= 0:
                pool["extra"] = meter.extra
                if meter.extra_blocks:
                    blockers.append(
                        {
                            "kind": "pool",
                            "label": pool["label"],
                            "left": 0,
                            "extra": meter.extra,
                        }
                    )
            pools.append(pool)
        known = [pool for pool in pools if pool["headroom"] is not None]
        binding = min(known, key=lambda pool: pool["headroom"]) if known else None
        return _Reading(machine_id, tuple(pools), tuple(blockers), binding)

    def best(self, selection: NativeLevelSelection) -> Optional[_Reading]:
        """The machine reading this selection launches on, blocked or not."""
        readings = [
            self.read(selection, m) for m in self.machines_for(selection.surface)
        ]
        if not readings:
            return None
        open_readings = [r for r in readings if not r.blockers]
        pick_from = open_readings or readings
        return max(pick_from, key=lambda r: _rank(r.headroom))


def evaluate_level_capacity(
    levels: Sequence[Level],
    *,
    meters: Sequence[Meter],
    offered: Sequence[tuple[str, str]],
    display: Callable[[str], str],
    native_models: dict,
    records: Sequence,
) -> list[dict[str, Any]]:
    """Report each base-model row's standing across observed native surfaces."""
    fleet = _Fleet(meters, offered)
    out = []
    for level in levels:
        options = []
        launchable = set()
        for entry in level.options:
            surfaces, blockers = set(), []
            for machine, surface in fleet.offered:
                selections, unavailable = native_selections(
                    entry,
                    surface=surface,
                    reading=native_models.get(machine, {}).get(surface),
                    records=records,
                )
                if unavailable:
                    blockers.append({"kind": "native", "label": unavailable})
                for selection in selections:
                    reading = fleet.read(selection, machine)
                    if reading.blockers:
                        blockers.extend(reading.blockers)
                    else:
                        surfaces.add(surface)
            launchable.update(surfaces)
            options.append(
                {
                    **entry.payload(),
                    "display_name": display(entry.model),
                    "now": {
                        "state": "can_launch" if surfaces else "blocked",
                        "surfaces": sorted(surfaces),
                        "blockers": []
                        if surfaces
                        else blockers
                        or [
                            {
                                "kind": "no_machine",
                                "label": "No usable machine offers this model.",
                            }
                        ],
                    },
                }
            )
        out.append(
            {
                "name": level.name,
                "glyph": level.glyph,
                "launchable_surfaces": [
                    surface
                    for surface in CLI_PLAN_LIMIT_SURFACES
                    if surface in launchable
                ],
                "options": options,
            }
        )
    return out


__all__ = ["Meter", "SURFACE_VENDORS", "evaluate_level_capacity", "pool_label"]
