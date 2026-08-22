"""Typed inputs and outcomes for fleet session launches."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Protocol, Sequence

from yoke_contracts.organization_contract.fleet_keys import FLEET_KEY_SPECS


LAUNCH_LEASE_SECONDS = 120
MAX_LAUNCH_LEASE_SECONDS = 300
DEFAULT_LAUNCH_DEADLINE_SECONDS = int(
    FLEET_KEY_SPECS["fleet.launch_deadline_minutes"].default
) * 60
DEFAULT_MAX_BODY_BYTES = int(FLEET_KEY_SPECS["fleet.max_body_bytes"].default)
MAX_LAUNCH_DEADLINE_SECONDS = 3600


class SessionLaunchError(ValueError):
    """A launch request or state transition was refused with a typed code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class LaunchAuthorization:
    """Verified caller decisions supplied by the registered-function boundary."""

    actor_id: int
    session_id: str | None
    can_operate_project: bool
    can_administer_project: bool = False


@dataclass(frozen=True)
class EligibleRelay:
    relay_id: str
    machine_id: str
    surface: str
    version: str
    last_seen_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EligibilitySnapshot:
    relays: tuple[EligibleRelay, ...]
    considered_machine_ids: tuple[str, ...] = ()
    rejection_codes: tuple[str, ...] = ()


class LaunchEligibilityPort(Protocol):
    """Derive launchable relays from current control-plane evidence."""

    def __call__(
        self,
        conn: Any,
        *,
        project_id: int,
        surface: str,
        machine_id: str | None,
        now: str,
    ) -> EligibilitySnapshot: ...


@dataclass(frozen=True)
class LaunchRequest:
    project_id: int
    executor_surface: str
    instructions: str
    idempotency_key: str
    machine_id: str | None = None
    model: str | None = None
    presentation: str | None = None
    allow_surface_fallback: bool = False
    deadline_seconds: int = DEFAULT_LAUNCH_DEADLINE_SECONDS


@dataclass(frozen=True)
class LaunchPreview:
    outcome: str
    requested_surface: str
    eligible_relays: tuple[EligibleRelay, ...]
    selected_relay: EligibleRelay | None = None

    @property
    def launchable(self) -> bool:
        return self.selected_relay is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "requested_surface": self.requested_surface,
            "launchable": self.launchable,
            "eligible_relays": [relay.to_dict() for relay in self.eligible_relays],
            "selected_relay": (
                self.selected_relay.to_dict() if self.selected_relay else None
            ),
        }


@dataclass(frozen=True)
class LaunchRecord:
    launch_id: str
    requester_actor_id: int
    requester_session_id: str | None
    project_id: int
    requested_surface: str
    requested_machine_id: str | None
    requested_model: str | None
    presentation_preference: str | None
    allow_surface_fallback: bool
    message_id: str
    idempotency_key: str | None
    state: str
    assigned_relay_id: str | None
    assigned_machine_id: str | None
    native_session_id: str | None
    attestation_hash: str | None
    attestation_consumed_at: str | None
    registered_session_id: str | None
    deadline_at: str
    created_at: str
    assigned_at: str | None
    launching_at: str | None
    awaiting_registration_at: str | None
    completed_at: str | None
    result_code: str | None
    result_evidence: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LaunchCreateOutcome:
    launch: LaunchRecord
    preview: LaunchPreview
    deduplicated: bool


@dataclass(frozen=True)
class LaunchClaim:
    launch: LaunchRecord
    attempt_id: str
    attempt_number: int
    lease_id: str
    lease_expires_at: str
    bootstrap_prompt: str
    attestation: str


@dataclass(frozen=True)
class LaunchRegistrationInjection:
    launch_id: str
    message_id: str
    session_id: str
    sender_actor_id: int
    body: str
    body_sha256: str


def ensure_operator(auth: LaunchAuthorization) -> None:
    if not auth.can_operate_project:
        raise SessionLaunchError(
            "permission_denied",
            f"actor {auth.actor_id} is not an operator for this project",
        )


def choose_relay(
    snapshot: EligibilitySnapshot,
    *,
    surface: str,
    machine_id: str | None,
) -> LaunchPreview:
    relays: Sequence[EligibleRelay] = snapshot.relays
    if not relays:
        outcome = (
            "unsupported_surface"
            if "unsupported_surface" in snapshot.rejection_codes
            else "no_eligible_relay"
        )
        return LaunchPreview(outcome, surface, tuple(relays))
    if len(relays) == 1:
        return LaunchPreview("assigned", surface, tuple(relays), relays[0])
    outcome = "relay_ambiguous" if machine_id else "machine_required"
    return LaunchPreview(outcome, surface, tuple(relays))


__all__ = [
    "DEFAULT_LAUNCH_DEADLINE_SECONDS",
    "DEFAULT_MAX_BODY_BYTES",
    "EligibilitySnapshot",
    "EligibleRelay",
    "LAUNCH_LEASE_SECONDS",
    "LaunchAuthorization",
    "LaunchClaim",
    "LaunchCreateOutcome",
    "LaunchEligibilityPort",
    "LaunchPreview",
    "LaunchRecord",
    "LaunchRegistrationInjection",
    "LaunchRequest",
    "MAX_LAUNCH_DEADLINE_SECONDS",
    "MAX_LAUNCH_LEASE_SECONDS",
    "SessionLaunchError",
    "choose_relay",
    "ensure_operator",
]
