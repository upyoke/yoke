"""Typed contracts for one machine-relay poll and its leased job."""

from __future__ import annotations

from datetime import datetime
from yoke_contracts.timestamps import temporal_wire
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Literal, Mapping, Sequence

from yoke_contracts.session_control.private_route_qualification import (
    PrivateRouteQualificationGrant,
)


LAUNCH_REPORT_CODES = frozenset({"native_created", "not_created", "outcome_unknown"})
LAUNCH_PROGRESS_CODE = "progress"

RelayJobKind = Literal["launch", "wake", "terminate", "evidence"]
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
    surface_confirmed_absent: Sequence[str] = ()
    surface_plan_limits: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    machine_capacity: Mapping[str, Any] = field(default_factory=dict)
    relay_health: Mapping[str, Any] = field(default_factory=dict)
    surface_native_models: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    credential_presence: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RelayPolicy:
    poll_seconds: int
    idle_after_minutes: int
    idle_poll_minutes: int
    max_wake_attempts: int

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
    target_native_thread_id: str | None = None
    #: The directory the target session already runs in. A wake carries it
    #: because the addressed item's project is not always the session's own,
    #: and a native conversation is resumable only from where it started.
    target_workspace: str | None = None
    target_launch_id: str | None = None
    requested_model: str | None = None
    requested_reasoning_effort: str | None = None
    requested_context_window_tokens: int | None = None
    presentation: str | None = None
    session_name: str | None = None
    deadline_at: datetime | None = None
    wake_mode: WakeMode | None = None
    target_liveness: str | None = None
    wake_route: str | None = None
    #: The target stamped ``mode=parked``: its turn is over by its own
    #: declaration, so a lingering vendor pid must not hold this wake.
    target_parked: bool = False
    launch_attestation: str | None = field(default=None, repr=False)
    #: The exact bounded question an evidence read carries to the machine:
    #: which kind, which file, how many lines, and the diagnostic references
    #: the control plane resolved for the target session.
    evidence_request: Mapping[str, Any] | None = None
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
        return temporal_wire(payload)


@dataclass(frozen=True)
class RelayClaimOutcome:
    """One poll's leased launch batch and optional serial control job."""

    relay_id: str
    machine_id: str
    state: Literal["active", "idle"]
    connected_until: datetime
    next_poll_seconds: int
    jobs: tuple[RelayJob, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "relay_id": self.relay_id,
            "machine_id": self.machine_id,
            "state": self.state,
            "connected_until": temporal_wire(self.connected_until),
            "next_poll_seconds": self.next_poll_seconds,
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
