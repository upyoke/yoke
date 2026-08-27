"""The liveness vocabulary shared by session listing and message selectors.

One spelling of the states a session row can be in, so the roster, the
recipient selector, and every adapter that offers a ``--liveness`` flag
accept and report the same words.

Deadness has three states; how a session became dead is a separate facet.
A session killed through ``session_control.session.terminate`` is ``ended``
like any other gone session — its ``terminated_at`` mechanics (no revival,
no wake, claims already released) are unchanged — and the kill shows up as
the ``killed`` ended cause rather than as a fourth liveness value.
"""

from __future__ import annotations

LIVENESS_ACTIVE = "active"
LIVENESS_STALE = "stale"
LIVENESS_ENDED = "ended"

#: The states a session row can be in, in narrowing-to-widening order.
LIVENESS_STATES: tuple[str, ...] = (
    LIVENESS_ACTIVE,
    LIVENESS_STALE,
    LIVENESS_ENDED,
)

#: Widening sentinel: every state, named explicitly by the caller.
LIVENESS_ALL = "all"

#: Accepted ``--liveness`` values wherever the flag widens a selector.
LIVENESS_CHOICES: tuple[str, ...] = (*LIVENESS_STATES, LIVENESS_ALL)

#: How an ``ended`` session got there. ``killed`` carries ``terminated_at``
#: and its permanent do-not-revive / do-not-wake mechanics; ``wound_down``
#: is an ordinary end, which the SessionEnd defense may still revive.
ENDED_CAUSE_KILLED = "killed"
ENDED_CAUSE_WOUND_DOWN = "wound_down"

#: Accepted ``--ended-cause`` values. A live session has no ended cause.
ENDED_CAUSES: tuple[str, ...] = (ENDED_CAUSE_KILLED, ENDED_CAUSE_WOUND_DOWN)


__all__ = [
    "ENDED_CAUSES",
    "ENDED_CAUSE_KILLED",
    "ENDED_CAUSE_WOUND_DOWN",
    "LIVENESS_ACTIVE",
    "LIVENESS_ALL",
    "LIVENESS_CHOICES",
    "LIVENESS_ENDED",
    "LIVENESS_STALE",
    "LIVENESS_STATES",
]
