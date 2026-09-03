"""Resolve a supervised Claude launch from control-plane registration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping
from uuid import UUID

from yoke_contracts.session_control.launch_registration import (
    REGISTERED_BUT_UNBOUND_CODE,
    REGISTERED_SESSION_INVALID_CODE,
)
from yoke_harness.session_relay_claude_identity import (
    CLAUDE_IDENTITY_LOOKUP_ATTEMPTS,
)


RegistrationResolver = Callable[[str], Mapping[str, object] | None]


@dataclass(frozen=True)
class ClaudeRegistrationResolution:
    session_id: str | None
    result_code: str
    attempts: int


def resolve_registered_session(
    resolver: RegistrationResolver | None,
    workspace: str,
    *,
    attempts: int = CLAUDE_IDENTITY_LOOKUP_ATTEMPTS,
) -> ClaudeRegistrationResolution:
    """Wait through the relay's bounded registration-candidate reads."""
    if resolver is None:
        return ClaudeRegistrationResolution(None, "registration_lookup_unavailable", 0)
    bounded = max(1, min(int(attempts), CLAUDE_IDENTITY_LOOKUP_ATTEMPTS))
    last_code = "registration_pending"
    for attempt in range(1, bounded + 1):
        try:
            result = resolver(workspace)
        except Exception:  # control-plane exception text stays private
            result = None
        if not isinstance(result, Mapping):
            last_code = "registration_lookup_failed"
            continue
        last_code = str(result.get("status") or "registration_pending")
        raw_session_id = result.get("session_id")
        if last_code not in {REGISTERED_BUT_UNBOUND_CODE, "registration_bound"}:
            continue
        try:
            session_id = str(UUID(str(raw_session_id or "")))
        except (TypeError, ValueError, AttributeError):
            return ClaudeRegistrationResolution(
                None, REGISTERED_SESSION_INVALID_CODE, attempt
            )
        return ClaudeRegistrationResolution(session_id, last_code, attempt)
    return ClaudeRegistrationResolution(None, last_code, bounded)


__all__ = [
    "ClaudeRegistrationResolution",
    "RegistrationResolver",
    "resolve_registered_session",
]
