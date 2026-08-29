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


def live_session_sql(alias: str) -> str:
    """SQL for the not-ended half of the roster, given a ``harness_sessions`` alias.

    A session is gone once either stamp is set, whichever put it there, and the
    two columns are independent. Every surface that splits the roster asks this
    one question rather than spelling a predicate of its own — a surface that
    tested only ``ended_at`` kept killed sessions on its live list.
    """
    return f"{alias}.ended_at IS NULL AND {alias}.terminated_at IS NULL"


def ended_session_sql(alias: str) -> str:
    """SQL for the ended half — the exact complement of :func:`live_session_sql`."""
    return f"({alias}.ended_at IS NOT NULL OR {alias}.terminated_at IS NOT NULL)"


def ended_at_sql(alias: str) -> str:
    """When an ended session ended: its ordinary end stamp, else its kill stamp.

    A killed session may carry only ``terminated_at``, so ordering or dating the
    ended roster on ``ended_at`` alone renders it blank and sorts it last.
    """
    return f"COALESCE({alias}.ended_at, {alias}.terminated_at)"


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
    "ended_at_sql",
    "ended_session_sql",
    "live_session_sql",
]
