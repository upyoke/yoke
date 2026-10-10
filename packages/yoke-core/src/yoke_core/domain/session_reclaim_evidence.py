"""Native reclaim activity facts and their owned wire evidence projection."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from yoke_contracts.timestamps import temporal_wire
from .session_reclaim_progress import open_tool_call_is_live, session_turn_is_running


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

    @property
    def open_tool_call_live(self) -> bool:
        """Whether the open tool-call row still evidences work in flight."""
        return open_tool_call_is_live(self.open_tool_call_at, self.activity_at)

    @property
    def in_flight(self) -> bool:
        return self.open_tool_call_live or session_turn_is_running(self.turn_posture)


@dataclass(frozen=True)
class ReclaimClassification:
    is_reclaimable: bool
    reason: str
    evidence: ReclaimActivityEvidence
