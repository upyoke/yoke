"""What level placement weighed: one option on one machine, and the result.

A candidate carries the machine's id, which launches and ``--machine`` key on,
and its registered name, which every reader-facing label shows instead.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from yoke_contracts.levels import Level
from yoke_contracts.refusal_recovery import compose_refusal

from yoke_core.domain.session_launch_capacity import MachineCapacity
from yoke_core.domain.session_launch_level_pools import PoolCheck


@dataclass(frozen=True)
class LevelCandidate:
    """One option weighed on one machine, and what decided it."""

    option_index: int
    surface: str
    model: str
    reasoning_effort: str
    context_window_tokens: int | None
    machine_id: str | None
    pools: tuple[PoolCheck, ...] = ()
    headroom_percent: float | None = None
    headroom_window: str | None = None
    live_workers: int | None = None
    blocked: str | None = None
    chosen: bool = False
    machine_name: str | None = None
    machine_capacity: tuple[MachineCapacity, ...] = ()

    @property
    def label(self) -> str:
        machine = self.machine_name or self.machine_id
        where = f" on {machine}" if machine else ""
        return f"{self.surface} {self.model} {self.reasoning_effort}{where}"

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["pools"] = [pool.to_dict() for pool in self.pools]
        out["machine_capacity"] = [
            reading.to_dict() for reading in self.machine_capacity
        ]
        out["label"] = self.label
        return out


@dataclass(frozen=True)
class LevelPlacement:
    """The level a launch asked for, every candidate weighed, and the winner."""

    level: str
    levels_source: str
    candidates: tuple[LevelCandidate, ...]
    chosen: LevelCandidate | None
    rule: str | None
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "levels_source": self.levels_source,
            "chosen": self.chosen.to_dict() if self.chosen else None,
            "rule": self.rule,
            "reason": self.reason,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
        }


def placement_refusal(
    level: Level, weighed: list[LevelCandidate], *, surface: str | None
) -> str:
    # Options that share one reason (every option, when no machine is usable)
    # share one clause, so the reason is not repeated once per option.
    by_reason: dict[str | None, list[str]] = {}
    for candidate in weighed:
        by_reason.setdefault(candidate.blocked, []).append(candidate.label)
    blocked = "; ".join(
        f"{', '.join(labels)}: {reason}" for reason, labels in by_reason.items()
    )
    return compose_refusal(
        f"No {level.name} option has capacity" + (f" on {surface}" if surface else ""),
        evaluated=blocked or (
            f"no level options are available on {surface}"
            if surface else "the level has no options"
        ),
        recovery=(
            f"Repeat launch create with --surface {surface} --model MODEL "
            "--reasoning-effort EFFORT using a qualifying selection from "
            "`yoke settings get levels`, or repair the named capacity or eligibility blocker."
            if surface else
            "Relaunch at another level with --level, wait for a named reset, "
            "or launch an exact selection with --surface"
        ),
    )


__all__ = ["LevelCandidate", "LevelPlacement"]
