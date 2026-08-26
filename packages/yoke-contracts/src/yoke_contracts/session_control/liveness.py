"""The liveness vocabulary shared by session listing and message selectors.

One spelling of the states a session row can be in, so the roster, the
recipient selector, and every adapter that offers a ``--liveness`` flag
accept and report the same words.
"""

from __future__ import annotations

LIVENESS_ACTIVE = "active"
LIVENESS_STALE = "stale"
LIVENESS_ENDED = "ended"
LIVENESS_TERMINATED = "terminated"

#: The states a session row can be in, in narrowing-to-widening order.
LIVENESS_STATES: tuple[str, ...] = (
    LIVENESS_ACTIVE,
    LIVENESS_STALE,
    LIVENESS_ENDED,
    LIVENESS_TERMINATED,
)

#: Widening sentinel: every state, named explicitly by the caller.
LIVENESS_ALL = "all"

#: Accepted ``--liveness`` values wherever the flag widens a selector.
LIVENESS_CHOICES: tuple[str, ...] = (*LIVENESS_STATES, LIVENESS_ALL)


__all__ = [
    "LIVENESS_ACTIVE",
    "LIVENESS_ALL",
    "LIVENESS_CHOICES",
    "LIVENESS_ENDED",
    "LIVENESS_STALE",
    "LIVENESS_STATES",
    "LIVENESS_TERMINATED",
]
