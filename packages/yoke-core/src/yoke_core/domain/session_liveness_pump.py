"""Keep the owning session live while it waits on a long local command.

The stale-session sweep reclaims a session whose newest activity signal is
older than its executor TTL — 20 minutes by default — and releases that
session's work claims when it does. A gate run routinely outlives that: a
registered Command case or a watcher-backed suite runs for 30 to 60
minutes while the session that started it sits idle waiting, so the sweep
reclaimed the item claim out from under a run that was still going and the
finished run could not record its own verdict.

Running the command IS the activity signal that was missing. Every long
command in Yoke goes through
:func:`yoke_core.tools._watch_runner.run_watcher`, which ticks this pump
while it relays the child's output; the pump refreshes the session
heartbeat — and, through it, the heartbeats of that session's active
claims — no more often than :data:`HEARTBEAT_INTERVAL_SECONDS`.

Liveness lasts exactly as long as the process does. Kill the run and the
refreshes stop, so the session goes stale on the normal schedule rather
than becoming immortal because something once claimed to be busy.
"""

from __future__ import annotations

import time
from typing import Callable, Optional

#: How often a running command refreshes its session's heartbeat. Well
#: inside the shortest stale TTL, so a single dropped refresh is not a
#: reclaim and the write cost stays negligible against a run measured in
#: tens of minutes.
HEARTBEAT_INTERVAL_SECONDS = 60.0


def _ambient_session_id() -> str:
    """The session this process belongs to, or empty when it has none."""
    try:
        from yoke_contracts.session_identity import resolve_ambient_session_id

        return str(resolve_ambient_session_id() or "")
    except Exception:  # noqa: BLE001 - no identity is a no-op, never a failure
        return ""


def refresh_session_heartbeat(session_id: str) -> bool:
    """Send one ``sessions.touch`` for *session_id*; report whether it landed.

    A refresh that cannot land — server offline, transport error, session
    already ended — must never take down the command being watched, which
    is the caller's real work. The run continues and the sweep's ordinary
    behavior resumes.
    """
    try:
        from yoke_contracts.api.function_call import ActorContext, TargetRef
        from yoke_core.api.service_client_structured_api_adapter import (
            call_dispatcher,
        )

        response = call_dispatcher(
            function_id="sessions.touch",
            target=TargetRef(kind="global"),
            payload={},
            actor=ActorContext(session_id=session_id),
            intent="long command liveness",
        )
    except Exception:  # noqa: BLE001 - liveness is best-effort by contract
        return False
    return bool(response.success)


class SessionLivenessPump:
    """Refresh one session's heartbeat while it waits on a long command."""

    def __init__(
        self,
        *,
        session_id: Optional[str] = None,
        interval_seconds: float = HEARTBEAT_INTERVAL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._interval = float(interval_seconds)
        self._clock = clock
        self._session_id = session_id
        self._resolved = session_id is not None
        # Starting the command is itself activity, so the first refresh
        # falls due one interval into the run rather than immediately.
        self._last_refresh = clock()

    def tick(self) -> bool:
        """Refresh the heartbeat when an interval has elapsed, else do nothing.

        Callers tick this once per relayed line, so the common path has to
        be two float operations and a comparison.
        """
        now = self._clock()
        if now - self._last_refresh < self._interval:
            return False
        self._last_refresh = now
        session_id = self._session()
        if not session_id:
            return False
        return refresh_session_heartbeat(session_id)

    def _session(self) -> str:
        """Resolve ambient identity once, on the first refresh that is due.

        Short commands never reach an interval, so a watcher run that
        finishes in milliseconds pays nothing for identity resolution. A
        process with no resolvable session stays inert for its whole run
        rather than re-probing every interval.
        """
        if not self._resolved:
            self._session_id = _ambient_session_id()
            self._resolved = True
        return self._session_id or ""


__all__ = [
    "HEARTBEAT_INTERVAL_SECONDS",
    "SessionLivenessPump",
    "refresh_session_heartbeat",
]
