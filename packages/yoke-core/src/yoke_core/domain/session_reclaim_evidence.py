"""Native reclaim activity facts and their owned wire evidence projection."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, Optional

from yoke_contracts.timestamps import temporal_wire
from .session_state import session_in_flight


@dataclass(frozen=True)
class ReclaimActivityEvidence:
    session_id: str
    executor: str
    effective_ttl_minutes: int
    last_heartbeat: datetime | None
    last_event_at: datetime | None
    claim_last_heartbeat: datetime | None
    claim_claimed_at: datetime | None
    episode_started_at: datetime | None
    activity_at: datetime | None
    ended_at: datetime | None
    turn_posture: Optional[str]
    open_tool_call_at: datetime | None

    session_facts: Mapping[str, Any] = field(default_factory=dict)

    def as_payload(self) -> dict:
        return temporal_wire(
            {
                "executor": self.executor,
                "effective_ttl_minutes": self.effective_ttl_minutes,
                "last_heartbeat": self.last_heartbeat,
                "last_event_at": self.last_event_at,
                "claim_last_heartbeat": self.claim_last_heartbeat,
                "claim_claimed_at": self.claim_claimed_at,
                "activity_at": self.activity_at,
                "turn_posture": self.turn_posture,
                "open_tool_call": self.open_tool_call_at is not None,
                "open_tool_call_at": self.open_tool_call_at,
            }
        )

    def is_in_flight(self, *, now: datetime | None = None) -> bool:
        return session_in_flight(
            {
                **self.session_facts,
                "ended_at": self.ended_at,
                "last_tool_call_at": self.last_event_at,
                "turn_posture": self.turn_posture,
                "open_tool_call_at": self.open_tool_call_at,
            },
            now=now,
        )

    @property
    def open_tool_call_live(self) -> bool:
        return self.is_in_flight()

    @property
    def in_flight(self) -> bool:
        return self.is_in_flight()


@dataclass(frozen=True)
class ReclaimClassification:
    is_reclaimable: bool
    reason: str
    evidence: ReclaimActivityEvidence
