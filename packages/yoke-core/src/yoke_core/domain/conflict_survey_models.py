"""Value objects emitted by direct-workflow conflict surveys."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class ConflictMatch:
    kind: str
    owner_item_id: Optional[int]
    path: str
    state: str
    detail: str


@dataclass(frozen=True)
class ConflictSurvey:
    item_id: int
    integration_target: str
    touch_paths: tuple[str, ...]
    blockers: tuple[ConflictMatch, ...]
    observed_at: str
    fingerprint: str

    @property
    def clear(self) -> bool:
        return not self.blockers

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": 1,
            "item_id": self.item_id,
            "integration_target": self.integration_target,
            "touch_paths": list(self.touch_paths),
            "blockers": [asdict(blocker) for blocker in self.blockers],
            "observed_at": self.observed_at,
            "fingerprint": self.fingerprint,
            "clear": self.clear,
        }


__all__ = ["ConflictMatch", "ConflictSurvey"]
