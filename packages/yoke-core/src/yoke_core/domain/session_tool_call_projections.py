"""Select expressions that read a session's tool-call state in one query.

Several readers need one fact about a session alongside the session row
itself — is it inside a running call, and what did it last finish? Each
is a correlated subquery over ``session_tool_calls``, and each is spliced
into a caller's own select list so the caller pays one query instead of
one per session.

They live apart from :mod:`yoke_core.domain.session_activity_state`, which
owns the writes, because these are read composition: a caller that only
projects a fact should not import the module that mutates it.

Both degrade to a constant absence on a fixture without the
``session_tool_calls`` table, matching the schema-tolerance contract the
writer module declares.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.session_activity_state import has_session_tool_calls_table

#: The waiter tool whose arming both the Stop gate and the orphan-waiter
#: detector recognise. It lives beside the projection that surfaces it so
#: neither reader has to import the other.
MONITOR_TOOL_NAME = "Monitor"


#: Column alias every reader of the open-call fact uses, so the predicate
#: that interprets it does not have to know which query produced it.
OPEN_TOOL_CALL_COLUMN = "open_tool_call_since"

#: Column alias for the session's most recently completed tool name.
LAST_COMPLETED_TOOL_COLUMN = "last_completed_tool"


def open_tool_call_select(conn: Any, *, session_alias: str) -> str:
    """A select expression for when a session's running tool call started.

    ``NULL`` unless the session's *latest* call is still open. Only the
    latest counts: an older open row belongs to a call whose completion
    was never recorded, which says nothing about whether the session is
    executing right now, while the newest one is the session's current
    stride. Callers use it to tell a silent session from a working one —
    no hook runs inside a tool call, so a long call and a stopped route
    are indistinguishable without this.

    The expression is prefixed with a comma for splicing into a select
    list, and degrades to a constant absence on a fixture with no
    ``session_tool_calls`` table, matching this module's schema-tolerance
    contract.
    """
    if not has_session_tool_calls_table(conn):
        return f",NULL AS {OPEN_TOOL_CALL_COLUMN}"
    return (
        ",(SELECT tc.started_at FROM session_tool_calls tc "
        f"WHERE tc.session_id={session_alias}.session_id "
        "AND tc.completed_at IS NULL "
        "AND tc.id=(SELECT MAX(tc2.id) FROM session_tool_calls tc2 "
        f"WHERE tc2.session_id={session_alias}.session_id)) "
        f"AS {OPEN_TOOL_CALL_COLUMN}"
    )


def last_completed_tool_select(conn: Any, *, session_alias: str) -> str:
    """A select expression naming the session's most recently finished tool.

    The Stop gate and the orphan-waiter detector both ask the same
    question — was the last thing this session finished a ``Monitor``? —
    and both used to answer it from the telemetry ledger, so an expired
    row silently turned "a waiter is armed" into "nothing is armed" and
    the gate stopped holding a Stop it should have held.

    ``session_tool_calls`` already records every call's identity, name,
    and completion, so the fact needs no new storage; it needs the query
    pointed at the state that owns it. Ordered by ``completed_at`` then
    ``id`` because two calls can share a stamp at second resolution and
    the later row is the later call.

    The expression is prefixed with a comma for splicing into a select
    list, and degrades to a constant absence on a fixture with no
    ``session_tool_calls`` table, matching this module's schema-tolerance
    contract.
    """
    if not has_session_tool_calls_table(conn):
        return f",NULL AS {LAST_COMPLETED_TOOL_COLUMN}"
    return (
        ",(SELECT tc.tool_name FROM session_tool_calls tc "
        f"WHERE tc.session_id={session_alias}.session_id "
        "AND tc.completed_at IS NOT NULL "
        "AND tc.tool_name IS NOT NULL AND tc.tool_name <> '' "
        "ORDER BY tc.completed_at DESC, tc.id DESC LIMIT 1) "
        f"AS {LAST_COMPLETED_TOOL_COLUMN}"
    )


__all__ = [
    "LAST_COMPLETED_TOOL_COLUMN",
    "MONITOR_TOOL_NAME",
    "OPEN_TOOL_CALL_COLUMN",
    "last_completed_tool_select",
    "open_tool_call_select",
]
