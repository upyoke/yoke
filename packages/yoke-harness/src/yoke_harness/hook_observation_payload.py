"""Native observation identity and its owned telemetry JSON boundary."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from yoke_contracts.timestamps import format_instant, parse_instant


@dataclass(frozen=True)
class PendingObservation:
    observation_id: str
    endpoint: str
    authorization: str
    observed_at: datetime
    hook_wait_ms: int
    hook_request: dict[str, Any]
    enqueued_at: float

    batch_field = "observations"

    def __post_init__(self) -> None:
        object.__setattr__(self, "observed_at", parse_instant(self.observed_at))

    def payload(self) -> dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "observed_at": format_instant(self.observed_at),
            "hook_wait_ms": self.hook_wait_ms,
            "hook_request": self.hook_request,
        }
