"""Typed contracts for one machine-relay poll and its leased job."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Literal, Mapping, Sequence

from yoke_contracts.session_control.private_route_qualification import (
    PrivateRouteQualificationGrant,
)


RelayJobKind = Literal["launch", "wake"]
WAKE_LEASE_SECONDS = 90
MAX_RELAY_LONG_POLL_SECONDS = 55
RELAY_LONG_POLL_STEP_SECONDS = 1


class WakeMode(str, Enum):
    """Scheduler authority for one native wake operation."""

    WAITING = "waiting"
    IDLE_TIMEOUT = "idle_timeout"


class SessionRelayError(ValueError):
    """A relay heartbeat, claim, or report was refused with a typed code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class RelayHeartbeat:
    relay_id: str
    actor_id: int
    machine_id: str
    hostname: str
    relay_version: str
    surface_versions: Mapping[str, str]
    project_ids: Sequence[int]


@dataclass(frozen=True)
class RelayPolicy:
    poll_seconds: int
    idle_after_minutes: int
    idle_poll_minutes: int
    max_wake_attempts: int
    launch_batch: int
    launch_stagger_seconds: int

    @property
    def idle_poll_seconds(self) -> int:
        return self.idle_poll_minutes * 60


@dataclass(frozen=True)
class RelayJob:
    job_kind: RelayJobKind
    job_id: str
    lease_id: str
    machine_id: str
    surface: str
    surface_version: str
    project_id: int
    native_instruction: str
    message_id: str | None = None
    target_session_id: str | None = None
    requested_model: str | None = None
    presentation: str | None = None
    wake_mode: WakeMode | None = None
    target_liveness: str | None = None
    wake_route: str | None = None
    launch_attestation: str | None = field(default=None, repr=False)
    private_route_qualification: PrivateRouteQualificationGrant | None = field(
        default=None,
        repr=False,
    )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if self.wake_mode is not None:
            payload["wake_mode"] = self.wake_mode.value
        if self.private_route_qualification is not None:
            payload["private_route_qualification"] = (
                self.private_route_qualification.model_dump(mode="json")
            )
        return payload


@dataclass(frozen=True)
class RelayClaimOutcome:
    """One poll's leased work: a launch batch, one wake, or nothing."""

    relay_id: str
    machine_id: str
    state: Literal["active", "idle"]
    connected_until: str
    next_poll_seconds: int
    launch_stagger_seconds: int = 0
    jobs: tuple[RelayJob, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "relay_id": self.relay_id,
            "machine_id": self.machine_id,
            "state": self.state,
            "connected_until": self.connected_until,
            "next_poll_seconds": self.next_poll_seconds,
            "launch_stagger_seconds": self.launch_stagger_seconds,
            "jobs": [job.to_dict() for job in self.jobs],
        }


__all__ = [
    "MAX_RELAY_LONG_POLL_SECONDS",
    "RELAY_LONG_POLL_STEP_SECONDS",
    "RelayClaimOutcome",
    "RelayHeartbeat",
    "RelayJob",
    "RelayJobKind",
    "RelayPolicy",
    "SessionRelayError",
    "WAKE_LEASE_SECONDS",
    "WakeMode",
]
