"""Resolve a vendor-created Cursor identity from launch registration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping
from uuid import UUID

from yoke_contracts.session_control.launch_registration import (
    REGISTERED_BUT_UNBOUND_CODE,
    REGISTERED_SESSION_INVALID_CODE,
)


CURSOR_REGISTRATION_LOOKUP_ATTEMPTS = 4
RegistrationResolver = Callable[[str], Mapping[str, object] | None]


@dataclass(frozen=True)
class CursorRegistrationResolution:
    session_id: str | None
    result_code: str
    attempts: int


def resolve_registered_session(
    resolver: RegistrationResolver | None,
    workspace: str,
    *,
    attempts: int = CURSOR_REGISTRATION_LOOKUP_ATTEMPTS,
) -> CursorRegistrationResolution:
    """Wait through bounded server-side registration-candidate reads.

    Cursor assigns a new chat's id, so the relay cannot name it on the native
    command line. The opening hook registers that id; this resolver then asks
    the existing launch-registration surface for the sole session matching
    the launch's machine, surface, workspace, and registration window.
    """
    if resolver is None:
        return CursorRegistrationResolution(None, "registration_lookup_unavailable", 0)
    bounded = max(1, min(int(attempts), CURSOR_REGISTRATION_LOOKUP_ATTEMPTS))
    last_code = "registration_pending"
    for attempt in range(1, bounded + 1):
        try:
            result = resolver(workspace)
        except Exception:
            result = None
        if not isinstance(result, Mapping):
            last_code = "registration_lookup_failed"
            continue
        last_code = str(result.get("status") or "registration_pending")
        if last_code not in {REGISTERED_BUT_UNBOUND_CODE, "registration_bound"}:
            continue
        try:
            session_id = str(UUID(str(result.get("session_id") or "")))
        except (AttributeError, TypeError, ValueError):
            return CursorRegistrationResolution(
                None, REGISTERED_SESSION_INVALID_CODE, attempt
            )
        return CursorRegistrationResolution(session_id, last_code, attempt)
    return CursorRegistrationResolution(None, last_code, bounded)


__all__ = [
    "CURSOR_REGISTRATION_LOOKUP_ATTEMPTS",
    "CursorRegistrationResolution",
    "RegistrationResolver",
    "resolve_registered_session",
]
