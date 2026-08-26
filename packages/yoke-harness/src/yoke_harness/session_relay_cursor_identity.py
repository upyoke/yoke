"""Bounded Cursor launch identity from ACP output and the conversation map.

``session/new`` on current cursor-agent returns a UUID ``sessionId``.
Registration still requires the first turn to fire hooks and write the
conversation map; a map miss is not proof the session registered. The
map wins when it holds a UUID (including a worktree fold). Unparseable
output records a bounded snippet and the parse expectation so the
attempt can fail closed and be retried.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import time
from typing import Callable
from uuid import UUID


CURSOR_IDENTITY_LOOKUP_ATTEMPTS = 4
CURSOR_IDENTITY_RETRY_SECONDS = 0.1
# Bounded well under the 300s relay lease so a stalled spawn fails fast
# and the launch can re-dispense instead of burning the lease silently.
CURSOR_REGISTRATION_WAIT_SECONDS = 20.0
CURSOR_REGISTRATION_RETRY_SECONDS = 0.5
CURSOR_REGISTRATION_TURN_WAIT_SECONDS = 15.0
IDENTITY_SNIPPET_LIMIT = 512
ACP_SESSION_PARSE_EXPECTATION = "JSON-RPC session/new result.sessionId UUID"
LaunchAttestationHandoff = Callable[..., bool]
ConversationLookup = Callable[[str], str | None]


@dataclass(frozen=True)
class CursorIdentityResolution:
    session_id: str | None
    result_code: str
    duration_ms: int
    attempts: int
    output_snippet: str | None = None
    parse_expectation: str | None = None


@dataclass(frozen=True)
class CursorLaunchBinding:
    result_code: str
    session_id: str | None
    duration_ms: int
    output_snippet: str | None = None
    parse_expectation: str | None = None


def bounded_identity_snippet(*parts: object) -> str:
    """Join stdout/stderr tails into one evidence-sized snippet."""
    chunks: list[str] = []
    for part in parts:
        if part is None:
            continue
        if isinstance(part, bytes):
            text = part.decode("utf-8", errors="replace")
        elif isinstance(part, (dict, list)):
            text = json.dumps(part, separators=(",", ":"))
        else:
            text = str(part)
        text = text.strip()
        if text:
            chunks.append(text)
    return "\n".join(chunks)[-IDENTITY_SNIPPET_LIMIT:]


def uuid_session_id(value: object) -> str | None:
    """Return a UUID session id, or None when the value is not one."""
    try:
        return str(UUID(str(value or "").strip()))
    except (AttributeError, TypeError, ValueError):
        return None


def session_id_from_native_payload(payload: object) -> str | None:
    """Parse the current cursor-agent ACP ``session/new`` identity."""
    if not isinstance(payload, dict):
        return None
    nested = payload.get("session")
    candidates = (
        payload.get("sessionId"),
        payload.get("session_id"),
        nested.get("sessionId") if isinstance(nested, dict) else None,
        nested.get("session_id") if isinstance(nested, dict) else None,
    )
    for value in candidates:
        parsed = uuid_session_id(value)
        if parsed:
            return parsed
    return None


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
    last_output = ""
    for attempt in range(1, attempts + 1):
        try:
            mapped = lookup(conversation_id)
        except Exception:
            result_code = "identity_lookup_failed"
        else:
            last_output = str(mapped).strip() if mapped else ""
            if last_output:
                return CursorIdentityResolution(
                    last_output,
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
        bounded_identity_snippet(last_output or "<empty>", conversation_id),
        ACP_SESSION_PARSE_EXPECTATION,
    )


def wait_for_conversation_session(
    conversation_id: str,
    lookup: ConversationLookup,
    *,
    wait_seconds: float = CURSOR_REGISTRATION_WAIT_SECONDS,
    retry_seconds: float = CURSOR_REGISTRATION_RETRY_SECONDS,
    sleeper: Callable[[float], None] = time.sleep,
) -> CursorIdentityResolution:
    """Poll the conversation map until hooks register, or the wait elapses."""
    retry = max(0.01, float(retry_seconds))
    attempts = max(1, int(max(0.0, float(wait_seconds)) / retry))
    started = time.monotonic()
    result_code = "registration_unproven"
    last_output = ""
    for attempt in range(1, attempts + 1):
        try:
            mapped = lookup(conversation_id)
        except Exception:
            result_code = "identity_lookup_failed"
        else:
            last_output = str(mapped).strip() if mapped else ""
            if last_output:
                return CursorIdentityResolution(
                    last_output,
                    "identity_resolved",
                    max(0, int((time.monotonic() - started) * 1000)),
                    attempt,
                )
            result_code = "registration_unproven"
        if attempt < attempts:
            sleeper(retry)
    return CursorIdentityResolution(
        None,
        result_code,
        max(0, int((time.monotonic() - started) * 1000)),
        attempts,
        bounded_identity_snippet(last_output or "<empty>", conversation_id),
        ACP_SESSION_PARSE_EXPECTATION,
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
    """Resolve launch identity and stage the attestation under that id."""
    resolution = resolve_conversation_session(
        conversation_id,
        lookup,
        sleeper=sleeper,
    )
    session_id = resolution.session_id
    if session_id is None:
        return CursorLaunchBinding(
            "registration_unproven",
            uuid_session_id(conversation_id),
            resolution.duration_ms,
            resolution.output_snippet or bounded_identity_snippet(conversation_id),
            resolution.parse_expectation or ACP_SESSION_PARSE_EXPECTATION,
        )
    token = str(attestation or "").strip()
    if not token or attestation_handoff is None:
        return CursorLaunchBinding(
            "attestation_handoff_unavailable",
            session_id,
            resolution.duration_ms,
        )
    try:
        staged = attestation_handoff(
            launch_id,
            token,
            binding_id=session_id,
        )
    except Exception:
        staged = False
    if not staged:
        return CursorLaunchBinding(
            "attestation_handoff_failed",
            session_id,
            resolution.duration_ms,
        )
    return CursorLaunchBinding(
        "native_created",
        session_id,
        resolution.duration_ms,
    )


__all__ = [
    "ACP_SESSION_PARSE_EXPECTATION",
    "CURSOR_IDENTITY_LOOKUP_ATTEMPTS",
    "CURSOR_IDENTITY_RETRY_SECONDS",
    "CURSOR_REGISTRATION_RETRY_SECONDS",
    "CURSOR_REGISTRATION_TURN_WAIT_SECONDS",
    "CURSOR_REGISTRATION_WAIT_SECONDS",
    "IDENTITY_SNIPPET_LIMIT",
    "ConversationLookup",
    "CursorIdentityResolution",
    "CursorLaunchBinding",
    "LaunchAttestationHandoff",
    "bind_launch_session",
    "bounded_identity_snippet",
    "conversation_map_lookup",
    "resolve_conversation_session",
    "session_id_from_native_payload",
    "uuid_session_id",
    "wait_for_conversation_session",
]
