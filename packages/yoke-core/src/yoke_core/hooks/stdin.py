"""Bounded stdin reads and first-prompt telemetry events.

Owns the ``select()``-bounded stdin path used by Stop / SessionEnd
fallback identity resolution and ``HarnessSessionSentFirstUserPromptSubmit``.
Re-exported via
``yoke_core.hooks.telemetry`` so post-cutover callers route
through one canonical telemetry surface.
"""

from __future__ import annotations
from pathlib import Path
from yoke_contracts.project_defaults import default_project_for_directory

import json
import os
import select
import sys
from typing import Any


STDIN_FALLBACK_TIMEOUT_SECONDS = 0.25
STDIN_FALLBACK_MAX_BYTES = 65536


def parse_json_payload(payload: str) -> dict[str, Any]:
    """Parse hook stdin into a dict, returning empty dict on malformed input."""
    if not payload:
        return {}
    try:
        data = json.loads(payload)
    except (json.JSONDecodeError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def bounded_stdin_read(
    max_bytes: int = STDIN_FALLBACK_MAX_BYTES,
    timeout: float = STDIN_FALLBACK_TIMEOUT_SECONDS,
) -> tuple[str, str]:
    """Read a bounded amount of data from stdin with a select() timeout.

    Returns ``(payload, state)`` where *state* is one of:

    - ``"empty"``   -- stdin had no data (or was a TTY / unreadable)
    - ``"bounded"`` -- read one or more bytes (possibly partial)
    - ``"timeout"`` -- select timed out before any data was available
    - ``"error"``   -- unexpected OSError reading stdin

    This never blocks forever; callers on the harness hot path can rely on it
    returning within *timeout* seconds even if the harness did not close stdin.
    """
    try:
        if sys.stdin is None or sys.stdin.closed:
            return "", "empty"
        if sys.stdin.isatty():
            return "", "empty"
    except (ValueError, OSError):
        return "", "empty"

    try:
        fd = sys.stdin.fileno()
    except (ValueError, OSError):
        return "", "empty"

    try:
        ready, _, _ = select.select([fd], [], [], timeout)
    except (OSError, ValueError):
        return "", "error"
    if not ready:
        return "", "timeout"

    try:
        chunk = os.read(fd, max_bytes)
    except OSError:
        return "", "error"
    if not chunk:
        return "", "empty"
    try:
        return chunk.decode("utf-8", errors="replace"), "bounded"
    except Exception:
        return "", "error"


def emit_harness_session_sent_first_user_prompt_submit(
    script_dir: str, session_id: str
) -> None:
    """Publish orientation telemetry for this session's first user prompt.

    Fires from the UserPromptSubmit handler at the end of the first-prompt
    orientation path, exactly once per session, on every harness — Claude,
    Codex, and Cursor all reach this one function. Semantically marks "the
    user has sent their first prompt to this session" — distinct from the
    earlier-firing HarnessSessionStarted event that marks "the session was
    registered in harness_sessions" (from the SessionStart hook).

    Registration owns the durable prompt stamp independently of this event.
    """
    del (
        script_dir
    )  # unused -- kept for API compat; native emitter resolves DB internally
    try:
        from yoke_core.domain.events import emit_event as _native_emit

        _native_emit(
            "HarnessSessionSentFirstUserPromptSubmit",
            event_kind="system",
            event_type="session_lifecycle",
            source_type="hook",
            severity="INFO",
            outcome="completed",
            session_id=session_id,
            project=default_project_for_directory(Path.cwd()),
            context={"hook": "UserPromptSubmit"},
        )
    except Exception:
        pass


__all__ = [
    "STDIN_FALLBACK_MAX_BYTES",
    "STDIN_FALLBACK_TIMEOUT_SECONDS",
    "bounded_stdin_read",
    "emit_harness_session_sent_first_user_prompt_submit",
    "parse_json_payload",
]
