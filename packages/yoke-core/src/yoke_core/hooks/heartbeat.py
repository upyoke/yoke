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

The heartbeat only refreshes an existing live row. A session whose row is
missing or ended is registered or revived by the dispatch tail's
register-on-first-sight (``yoke_core.hooks.registration
.ensure_registered_from_hook``), which runs wherever the chain runs and
binds the verified actor and the client's own identity facts.

No new event names are introduced — tool-call liveness is already
covered by ``harness_sessions.last_tool_call_at`` (stamped by the
observe pipeline, read by
:func:`yoke_core.domain.session_reclaim_activity.latest_activity`).
This module re-stamps ``last_heartbeat`` for telemetry dashboards and
as belt-and-suspenders defense for the 60s SessionEnd recovery window
when tool events lag.
"""

from __future__ import annotations

from yoke_core.hooks.types import (
    HookContext,
    HookDecision,
    Next,
    Outcome,
)


_BUSY_TIMEOUT_MS = 5000


def _heartbeat_session(session_id: str) -> None:
    """Best-effort heartbeat update. Never raises."""
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
        heartbeat(conn, session_id)
    except SessionError:
        # NOT_FOUND / SESSION_ENDED: the dispatch tail registers or
        # revives the row for this same hook.
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
            _heartbeat_session(sid)
    except Exception:
        pass
    return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)


__all__ = ["evaluate"]
