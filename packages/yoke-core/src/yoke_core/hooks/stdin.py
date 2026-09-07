"""Bounded stdin reads + hook-failure / first-prompt telemetry events.

Owns the ``select()``-bounded stdin path used by Stop / SessionEnd
fallback identity resolution, plus the two telemetry events emitted
from the surrounding handlers: ``HarnessSessionHookFailed`` and
``HarnessSessionSentFirstUserPromptSubmit``. Re-exported via
``yoke_core.hooks.telemetry`` so post-cutover callers route
through one canonical telemetry surface.
"""

from __future__ import annotations

import json
import os
import select
import sys
from typing import Any, Optional


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


def emit_session_hook_failed(
    *,
    hook_event: str,
    executor: str,
    reason: str,
    latency_ms: int,
    stdin_state: str,
    session_id_source: str,
    session_id: str = "",
    service_client_path: str = "",
    extra: Optional[dict[str, Any]] = None,
) -> None:
    """Emit a ``HarnessSessionHookFailed`` event via the native Python emitter.

    Non-fatal: any exception is swallowed so that the hook path cannot itself
    crash the harness close sequence.
    """
    context: dict[str, Any] = {
        "hook_event": hook_event,
        "executor": executor,
        "reason": reason,
        "latency_ms": int(latency_ms),
        "stdin_state": stdin_state,
        "session_id_source": session_id_source,
    }
    if service_client_path:
        context["service_client_path"] = service_client_path
    if extra:
        context.update(extra)

    try:
        from yoke_core.domain.events import emit_event as _emit

        _emit(
            "HarnessSessionHookFailed",
            event_kind="system",
            event_type="session_hook_failure",
            source_type="hook",
            session_id=session_id or "unknown",
            severity="WARN",
            outcome="failed",
            project="yoke",
            hook_event_name=hook_event,
            context=context,
        )
    except Exception:
        return


def _stamp_first_user_prompt(session_id: str) -> None:
    """Record the prompt boundary on the session row.

    The durable half of the pair below. A probe session is one that never
    received a prompt, and reading that from telemetry meant a real
    conversation answered inside thirty seconds turned into a probe — and
    vanished from the operator's session list — the moment its event
    expired. The stamp is write-once and never expires.

    Runs where the control plane is local; a relayed client has nothing
    to write to and returns, exactly as the emission below degrades.
    """
    if not session_id:
        return
    try:
        from yoke_core.domain import db_backend
        from yoke_core.domain.control_plane_transport import local_connection_or_none
        from yoke_core.domain.session_message_types import timestamp, utc_now
        from yoke_core.domain.session_recovery_facts import stamp_first_user_prompt

        conn = local_connection_or_none(db_backend.connect)
        if conn is None:
            return
        try:
            stamp_first_user_prompt(conn, session_id, timestamp(utc_now()))
            conn.commit()
        finally:
            conn.close()
    except Exception:
        return


def emit_harness_session_sent_first_user_prompt_submit(
    script_dir: str, session_id: str
) -> None:
    """Record and publish this session's first user prompt.

    Fires from the UserPromptSubmit handler at the end of the first-prompt
    orientation path, exactly once per session, on every harness — Claude,
    Codex, and Cursor all reach this one function. Semantically marks "the
    user has sent their first prompt to this session" — distinct from the
    earlier-firing HarnessSessionStarted event that marks "the session was
    registered in harness_sessions" (from the SessionStart hook).

    The session stamp is the durable record readers consult; the event is
    the telemetry beside it.
    """
    del (
        script_dir
    )  # unused -- kept for API compat; native emitter resolves DB internally
    _stamp_first_user_prompt(session_id)
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
            project="yoke",
            context={"hook": "UserPromptSubmit"},
        )
    except Exception:
        pass


__all__ = [
    "STDIN_FALLBACK_MAX_BYTES",
    "STDIN_FALLBACK_TIMEOUT_SECONDS",
    "bounded_stdin_read",
    "emit_harness_session_sent_first_user_prompt_submit",
    "emit_session_hook_failed",
    "parse_json_payload",
]
