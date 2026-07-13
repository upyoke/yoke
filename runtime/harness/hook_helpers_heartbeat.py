"""PreToolUse heartbeat refresh — attestable-activity primitive.

Lifts the ``harness_sessions.last_heartbeat`` write onto the agent's
tool-call turn boundary, replacing the deleted background keepalive
loop. Heartbeat now happens once per
agent turn instead of once per 60s background tick, so the DB-write
floor drops to whatever the active session emits.

Contract: ``evaluate(record: HookContext) -> HookDecision``. The hook
is telemetry-style: it never blocks tool execution and never raises;
every failure path collapses to ``HookDecision(outcome=NOOP,
next=CONTINUE)``.

No new event names are introduced — tool-call liveness is already
covered by ``harness_sessions.last_tool_call_at`` (stamped by the
observe pipeline, read by
:func:`yoke_core.domain.session_reclaim_activity.latest_activity`).
This module re-stamps ``last_heartbeat`` for telemetry dashboards and
as belt-and-suspenders defense for the 60s SessionEnd recovery window
when tool events lag.
"""

from __future__ import annotations

import os
from typing import Optional

from runtime.harness.hook_runner.types import (
    HookContext,
    HookDecision,
    Next,
    Outcome,
)


_BUSY_TIMEOUT_MS = 5000


def _fallback_model(record: HookContext) -> str:
    payload = record.payload if isinstance(record.payload, dict) else {}
    raw = payload.get("model")
    return raw if isinstance(raw, str) and raw.strip() else "unknown"


def _fallback_workspace(record: HookContext) -> str:
    if isinstance(record.cwd, str) and record.cwd.strip():
        return record.cwd
    return os.getcwd()


def _has_executor_env_signal() -> bool:
    return any(
        os.environ.get(key)
        for key in ("YOKE_EXECUTOR", "CODEX_THREAD_ID", "CLAUDE_CODE_ENTRYPOINT")
    )


def _compatible_entrypoint(
    executor: str,
    entrypoint: Optional[str],
) -> Optional[str]:
    if not entrypoint:
        return None
    ex = executor.strip().lower()
    ep = entrypoint.strip().lower()
    if ex.startswith("claude") and ep.startswith("codex"):
        return None
    if ex.startswith("codex") and ep.startswith("claude"):
        return None
    return entrypoint


def _backfill_session(conn, session_id: str, record: HookContext) -> None:
    """Register or reactivate a session that missed SessionStart."""
    from runtime.harness.hook_runner.session_lifecycle_client import (
        register_harness_session,
    )
    from runtime.harness.hook_helpers_identity import (
        compose_executor_from_entrypoint,
        detect_entrypoint,
        detect_executor,
        detect_provider,
    )

    entrypoint = detect_entrypoint()
    executor = (
        record.executor_surface
        or record.executor_family
        or (detect_executor() if _has_executor_env_signal() else "unknown")
    )
    entrypoint = _compatible_entrypoint(executor, entrypoint)
    executor = compose_executor_from_entrypoint(executor, entrypoint)
    provider = detect_provider(executor)
    register_harness_session(
        root=_fallback_workspace(record),
        session_id=session_id,
        executor=executor,
        provider=provider,
        model=_fallback_model(record),
        entrypoint=entrypoint,
    )


def _relay_owns_session_authority() -> bool:
    """True when the active transport is https, so the session row lives on
    the connected server rather than any local DB.

    Mirrors ``session_lifecycle_client._relay_owns_registration``. The local
    ``db_backend.connect()`` below is the right authority only when the
    session row is local (local-postgres transport, or the server process
    itself running the relayed hook). A defensive guard so a client-side
    in-process invocation on an https machine can never silently heartbeat a
    local DB. Any config read failure resolves False so local-transport
    behavior is untouched.
    """
    try:
        from yoke_core.domain.machine_config import active_connection
        from yoke_contracts.machine_config.schema import TRANSPORT_HTTPS

        return str(active_connection().get("transport") or "") == TRANSPORT_HTTPS
    except Exception:  # never break the telemetry heartbeat on config
        return False


def _heartbeat_session(session_id: str, record: HookContext) -> None:
    """Best-effort heartbeat update/backfill. Never raises."""
    if _relay_owns_session_authority():
        # https: the session row is server-side. The relay path runs this
        # heartbeat server-side (where the transport is local-postgres);
        # a client-side in-process call must not write a local DB.
        return
    try:
        from yoke_core.domain.sessions import SessionError
        from yoke_core.domain.sessions_lifecycle_registry import heartbeat
        from yoke_core.domain import db_backend
    except Exception:
        return
    try:
        conn = db_backend.connect(busy_timeout_ms=_BUSY_TIMEOUT_MS)
    except Exception:
        return
    try:
        try:
            heartbeat(conn, session_id)
        except SessionError as exc:
            if exc.code in {"NOT_FOUND", "SESSION_ENDED"}:
                try:
                    _backfill_session(conn, session_id, record)
                except Exception:
                    pass
        except Exception:
            pass
    finally:
        try:
            conn.close()
        except Exception:
            pass


def evaluate(record: HookContext) -> HookDecision:
    """Refresh heartbeat for ``record.session_id`` when present.

    Returns ``HookDecision(outcome=NOOP, next=CONTINUE)`` — the
    PreToolUse hook chain is never blocked by this module. Every
    failure (missing db, ended session, schema mismatch, backend
    errors) swallows into the same NOOP so the chain
    advances unconditionally.
    """
    try:
        sid = record.session_id
        if sid and sid != "unknown":
            _heartbeat_session(sid, record)
    except Exception:
        pass
    return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)


__all__ = ["evaluate"]
