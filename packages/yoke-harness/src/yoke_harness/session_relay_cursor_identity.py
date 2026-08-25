"""Bounded Cursor conversation-map identity for ACP-created launches.

ACP ``session/new`` returns a conversation id, not the session the hook
registers. Registration matches ``native_session_id`` exactly, so the
adapter waits for the conversation map the way Claude waits for the
backgrounded UUID, then stages the attestation sidecar under that id.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time
from typing import Callable


CURSOR_IDENTITY_LOOKUP_ATTEMPTS = 4
CURSOR_IDENTITY_RETRY_SECONDS = 0.1
LaunchAttestationHandoff = Callable[..., bool]
ConversationLookup = Callable[[str], str | None]


@dataclass(frozen=True)
class CursorIdentityResolution:
    session_id: str | None
    result_code: str
    duration_ms: int
    attempts: int


@dataclass(frozen=True)
class CursorLaunchBinding:
    result_code: str
    session_id: str | None
    duration_ms: int


def conversation_map_lookup(
    conversation_id: str,
    map_dir: Path | None = None,
) -> str | None:
    """Read one conversation-map entry from the machine home map directory."""
    from yoke_cli.config import machine_config
    from yoke_contracts.cursor_session_map import (
        CURSOR_SESSION_MAP_DIR_NAME,
        recorded_session_id_for_conversation,
    )

    directory = map_dir or (machine_config.yoke_home() / CURSOR_SESSION_MAP_DIR_NAME)
    mapped = recorded_session_id_for_conversation(directory, conversation_id)
    return mapped.strip() if isinstance(mapped, str) and mapped.strip() else None


def resolve_conversation_session(
    conversation_id: str,
    lookup: ConversationLookup,
    *,
    attempts: int = CURSOR_IDENTITY_LOOKUP_ATTEMPTS,
    retry_seconds: float = CURSOR_IDENTITY_RETRY_SECONDS,
    sleeper: Callable[[float], None] = time.sleep,
) -> CursorIdentityResolution:
    """Retry a bounded number of map reads until a session id is present."""
    attempts = max(1, min(int(attempts), CURSOR_IDENTITY_LOOKUP_ATTEMPTS))
    started = time.monotonic()
    result_code = "identity_parse_failed"
    for attempt in range(1, attempts + 1):
        try:
            mapped = lookup(conversation_id)
        except Exception:
            result_code = "identity_lookup_failed"
        else:
            session_id = str(mapped).strip() if mapped else ""
            if session_id:
                return CursorIdentityResolution(
                    session_id,
                    "identity_resolved",
                    max(0, int((time.monotonic() - started) * 1000)),
                    attempt,
                )
            result_code = "identity_parse_failed"
        if attempt < attempts:
            sleeper(max(0.0, retry_seconds))
    return CursorIdentityResolution(
        None,
        result_code,
        max(0, int((time.monotonic() - started) * 1000)),
        attempts,
    )


def bind_launch_session(
    conversation_id: str,
    lookup: ConversationLookup,
    attestation_handoff: LaunchAttestationHandoff | None,
    launch_id: str,
    attestation: str,
    *,
    sleeper: Callable[[float], None] = time.sleep,
) -> CursorLaunchBinding:
    """Resolve the mapped session and stage the launch attestation under it."""
    resolution = resolve_conversation_session(
        conversation_id,
        lookup,
        sleeper=sleeper,
    )
    if resolution.session_id is None:
        return CursorLaunchBinding(
            resolution.result_code,
            None,
            resolution.duration_ms,
        )
    token = str(attestation or "").strip()
    if not token or attestation_handoff is None:
        return CursorLaunchBinding(
            "attestation_handoff_unavailable",
            resolution.session_id,
            resolution.duration_ms,
        )
    try:
        staged = attestation_handoff(
            launch_id,
            token,
            binding_id=resolution.session_id,
        )
    except Exception:
        staged = False
    if not staged:
        return CursorLaunchBinding(
            "attestation_handoff_failed",
            resolution.session_id,
            resolution.duration_ms,
        )
    return CursorLaunchBinding(
        "native_created",
        resolution.session_id,
        resolution.duration_ms,
    )


__all__ = [
    "CURSOR_IDENTITY_LOOKUP_ATTEMPTS",
    "CURSOR_IDENTITY_RETRY_SECONDS",
    "ConversationLookup",
    "CursorIdentityResolution",
    "CursorLaunchBinding",
    "LaunchAttestationHandoff",
    "bind_launch_session",
    "conversation_map_lookup",
    "resolve_conversation_session",
]
