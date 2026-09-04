"""Shared definition of a probe session — a harness's own startup artifact.

Clicking "New" in Claude Desktop, or activating the VS Code extension,
spawns a ``claude`` process that registers a session, sends no prompt, calls
no tool, and ends about a second later. Those rows are real audit history
and stay in ``harness_sessions``; what they must not do is present
themselves to an operator as sessions doing work — one click produced three
session cards where one conversation existed.

One predicate decides what a probe is, and every session reader consumes it:
the Sessions page and the Overview sessions band (both served by
``sessions.list`` through
:func:`yoke_core.domain.sessions_list_read.list_sessions`) and the steering
fleet report's session counts
(:mod:`yoke_core.domain.steering_fleet_report_capacity`).

A session qualifies only once it has ended, because the three facts that
identify a probe are jointly true only of a finished session: it ended
within :data:`PROBE_MAX_LIFETIME_SECONDS` of offering itself, it called no
tool, and it never reported a first user prompt. A live session that has
done nothing yet is a session that has not done anything *yet*, and a
predicate that did not wait for the end would hide every real session for
its first seconds.
"""

from __future__ import annotations


#: How long after ``offered_at`` a session may end and still be read as a
#: harness startup probe rather than a conversation that ended quickly.
PROBE_MAX_LIFETIME_SECONDS = 30

#: The event a session emits once its operator's first prompt has been
#: handled. Its absence is what separates a probe from a real session that
#: was answered and closed inside the window.
FIRST_USER_PROMPT_EVENT_NAME = "HarnessSessionSentFirstUserPromptSubmit"


def probe_session_sql(alias: str = "s") -> str:
    """Return the SQL predicate that is true for a probe session row.

    *alias* is the ``harness_sessions`` alias (or table name) in the caller's
    query. The fragment is self-contained and parameter-free, so it composes
    into any ``WHERE`` clause without disturbing the caller's binds.
    """

    return (
        f"({alias}.ended_at IS NOT NULL"
        f" AND {alias}.tool_call_count = 0"
        f" AND {alias}.ended_at::timestamptz - {alias}.offered_at::timestamptz"
        f" <= interval '{PROBE_MAX_LIFETIME_SECONDS} seconds'"
        " AND NOT EXISTS (SELECT 1 FROM events e"
        f" WHERE e.session_id = {alias}.session_id"
        f" AND e.event_name = '{FIRST_USER_PROMPT_EVENT_NAME}'))"
    )


def not_probe_session_sql(alias: str = "s") -> str:
    """Return the SQL predicate every operator-facing session read applies."""

    return f"NOT {probe_session_sql(alias)}"


__all__ = [
    "FIRST_USER_PROMPT_EVENT_NAME",
    "PROBE_MAX_LIFETIME_SECONDS",
    "not_probe_session_sql",
    "probe_session_sql",
]
