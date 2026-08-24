"""Bounded Claude background-agent to native-session identity resolution."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
import time
from typing import Callable
from uuid import UUID

from yoke_harness.session_relay_claude_process import ClaudeProcessResult


CLAUDE_IDENTITY_LOOKUP_ATTEMPTS = 4
CLAUDE_IDENTITY_RETRY_SECONDS = 0.1
_BACKGROUND_ID_PATTERN = re.compile(
    r"(?im)^\s*backgrounded\s*[·:]\s*([A-Za-z0-9_-]{4,64})\s*$"
)


@dataclass(frozen=True)
class ClaudeIdentityResolution:
    session_id: str | None
    result_code: str
    returncode: int
    duration_ms: int
    attempts: int


def background_agent_id(process: ClaudeProcessResult) -> str | None:
    matched = _BACKGROUND_ID_PATTERN.search(f"{process.stdout}\n{process.stderr}")
    return matched.group(1) if matched else None


def _session_id(short_id: str, output: str) -> str | None:
    try:
        document = json.loads(output)
    except (TypeError, ValueError):
        return None
    if isinstance(document, dict):
        document = document.get("agents", document.get("sessions"))
    if not isinstance(document, list):
        return None
    matches = set()
    for row in document:
        if not isinstance(row, dict):
            continue
        row_id = row.get("id") or row.get("agentId") or row.get("shortId")
        if str(row_id or "") != short_id:
            continue
        try:
            matches.add(str(UUID(str(row.get("sessionId") or ""))))
        except (TypeError, ValueError, AttributeError):
            continue
    return matches.pop() if len(matches) == 1 else None


def resolve_background_session(
    short_id: str,
    lookup: Callable[[], ClaudeProcessResult],
    *,
    attempts: int = CLAUDE_IDENTITY_LOOKUP_ATTEMPTS,
    retry_seconds: float = CLAUDE_IDENTITY_RETRY_SECONDS,
    sleeper: Callable[[float], None] = time.sleep,
) -> ClaudeIdentityResolution:
    """Retry a bounded number of listings until the actual UUID is present."""
    attempts = max(1, min(int(attempts), CLAUDE_IDENTITY_LOOKUP_ATTEMPTS))
    duration_ms = 0
    returncode = 0
    result_code = "identity_parse_failed"
    for attempt in range(1, attempts + 1):
        try:
            process = lookup()
        except Exception:  # native exception text can contain private output
            result_code = "identity_lookup_failed"
        else:
            duration_ms += max(0, process.duration_ms)
            returncode = process.returncode
            if process.returncode:
                result_code = "identity_lookup_failed"
            else:
                session_id = _session_id(short_id, process.stdout)
                if session_id is not None:
                    return ClaudeIdentityResolution(
                        session_id,
                        "identity_resolved",
                        returncode,
                        duration_ms,
                        attempt,
                    )
                result_code = "identity_parse_failed"
        if attempt < attempts:
            sleeper(max(0.0, retry_seconds))
    return ClaudeIdentityResolution(
        None,
        result_code,
        returncode,
        duration_ms,
        attempts,
    )
