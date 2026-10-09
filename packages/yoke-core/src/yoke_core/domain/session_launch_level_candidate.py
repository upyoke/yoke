"""What level placement weighed: one option on one machine, and the result.

A candidate carries the machine's id, which launches and ``--machine`` key on,
and its registered name, which every reader-facing label shows instead.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

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
    fallback: bool
    pools: tuple[PoolCheck, ...] = ()
    headroom_percent: float | None = None
    headroom_window: str | None = None
    live_workers: int = 0
    blocked: str | None = None
    chosen: bool = False
    machine_name: str | None = None

    @property
    def label(self) -> str:
        machine = self.machine_name or self.machine_id
        where = f" on {machine}" if machine else ""
        via = " (fallback)" if self.fallback else ""
        return f"{self.surface} {self.model} {self.reasoning_effort}{via}{where}"

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["pools"] = [pool.to_dict() for pool in self.pools]
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


__all__ = ["LevelCandidate", "LevelPlacement"]
