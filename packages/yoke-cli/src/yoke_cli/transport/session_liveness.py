"""Session liveness probes and keepalive for client-side waits.

The anchor-contention healer (:mod:`yoke_contracts.session_anchor_contention`)
drops a recorded contender only on a positive answer that its session ended.
This probe supplies that answer over whichever transport the machine uses,
via the ``sessions.list`` single-session projection — a stale session counts
as live, because a quiet conversation's background children still run under
its identity.

Lives in the transport layer so both anchor writers — the engine-side shim
and the harness hook client — share one implementation.

Client-side polling commands also live outside the engine process.  Their
single-shot reads can wait longer than the stale-session TTL, so
:class:`ClientSessionLiveness` periodically dispatches ``sessions.touch``
through the same connection while the command remains in flight.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Optional

from yoke_contracts.api.function_call import ActorContext, TargetRef


_Dispatch = Callable[..., Any]


def refresh_session_heartbeat(
    actor: ActorContext,
    *,
    dispatch: Optional[_Dispatch] = None,
) -> bool:
    """Best-effort ``sessions.touch`` for the actor owning a client wait."""
    if not actor.session_id:
        return False
    try:
        if dispatch is None:
            from yoke_cli.transport.dispatcher import call_dispatcher

            dispatch = call_dispatcher
        response = dispatch(
            function_id="sessions.touch",
            target=TargetRef(kind="global"),
            payload={},
            actor=actor,
            intent="long command liveness",
        )
    except Exception:  # noqa: BLE001 — liveness cannot replace the real work
        return False
    return bool(response.success)


class ClientSessionLiveness:
    """Keep one CLI actor live for the duration of a polling command."""

    def __init__(
        self,
        actor: ActorContext,
        *,
        interval_seconds: float,
        dispatch: Optional[_Dispatch] = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._actor = actor
        self._interval = float(interval_seconds)
        if self._interval <= 0:
            raise ValueError("interval_seconds must be positive")
        self._dispatch = dispatch
        self._clock = clock
        self._last_refresh = clock()

    def tick(self) -> bool:
        """Refresh when the cadence is due; cheap enough for every poll tick."""
        now = self._clock()
        if now - self._last_refresh < self._interval:
            return False
        self._last_refresh = now
        return refresh_session_heartbeat(
            self._actor,
            dispatch=self._dispatch,
        )


def contender_is_live(session_id: str) -> Optional[bool]:
    """``True`` live (active or stale), ``False`` not a live session, ``None`` unknown.

    A successful probe that finds *no row* answers ``False``: session rows
    are never deleted — ended conversations keep theirs — so an id with
    positively no registration is not a conversation on this control plane
    (the anchor-poisoning class is exactly such ids). The one race, a
    brand-new session probed before its first registration flush, self
    corrects: its next anchor write re-contends the pid. ``None`` is
    reserved for an answer that is not about the probed session — a failed
    probe (transport down, refused call), or a server that predates the
    ``session_id`` filter and returns the roster instead of the projection;
    only a row that names the probed id may answer for it. The healer keeps
    unknowns, so genuine ambiguity stays fail-closed.
    """
    if not session_id:
        return None
    try:
        from yoke_cli.transport.dispatcher import call_dispatcher

        response = call_dispatcher(
            function_id="sessions.list",
            target=TargetRef(kind="global"),
            payload={"session_id": session_id},
        )
    except Exception:  # noqa: BLE001 — probe failure is "unknown"
        return None
    if not response.success:
        return None
    rows = (response.result or {}).get("rows") or []
    if not rows:
        return False
    for row in rows:
        if str(row.get("session_id") or "") == session_id:
            return str(row.get("liveness") or "") != "ended"
    return None


__all__ = [
    "ClientSessionLiveness",
    "contender_is_live",
    "refresh_session_heartbeat",
]
