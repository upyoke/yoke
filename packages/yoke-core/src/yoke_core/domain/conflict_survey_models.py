"""Value objects emitted by direct-workflow conflict surveys."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from yoke_contracts.timestamps import format_instant
from yoke_contracts import conflict_survey as survey_contract
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
    observed_at: datetime
    fingerprint: str
    no_changes: bool = False

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
            "observed_at": format_instant(self.observed_at),
            "fingerprint": self.fingerprint,
            "clear": self.clear,
            "no_changes": self.no_changes,
        }


@dataclass(frozen=True)
class ConflictSurveyReservation:
    """Compare-and-swap marker for one in-flight survey request."""

    content: str
    previous_content: Optional[str]


@dataclass(frozen=True)
class RecordedConflictSurvey:
    """One durable survey row classified before callers consume it."""

    state: survey_contract.ConflictSurveyRecordState
    payload: Optional[dict[str, Any]] = None


__all__ = [
    "ConflictMatch",
    "ConflictSurvey",
    "ConflictSurveyReservation",
    "RecordedConflictSurvey",
]
