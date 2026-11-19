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

from yoke_core.domain.schema_common import _get_columns
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

#: Aliases for the subagent work since the parent's own last call: which
#: agent made the newest child call, when that run of child calls began, and
#: when the newest child call started if it is still open.
CHILD_AGENT_TYPE_COLUMN = "child_agent_type"
CHILD_ACTIVITY_SINCE_COLUMN = "child_activity_since"
OPEN_CHILD_CALL_COLUMN = "open_child_call_since"


def _child_marked(conn: Any) -> bool:
    return "agent_type" in set(_get_columns(conn, "session_tool_calls"))


def _parent_rows(alias: str) -> str:
    """Only the parent's own calls: a subagent's row names its agent_type.

    A subagent shares its parent's session id, and its calls say nothing
    about the parent's turn: no parent hook runs inside them.
    """
    return f" AND {alias}.agent_type IS NULL"


def open_tool_call_select(conn: Any, *, session_alias: str) -> str:
    """A select expression for when a session's running tool call started.

    ``NULL`` unless the session's *latest* call is still open. Only the
    latest counts: an older open row belongs to a call whose completion
    was never recorded, which says nothing about whether the session is
    executing right now, while the newest one is the session's current
    stride. Callers use it to tell a silent session from a working one —
    no hook runs inside a tool call, so a long call and a stopped route
    are indistinguishable without this.

    Current means the session's highest ``id``. Start reconciliation can
    move ``started_at`` earlier on an existing row, and a later-started
    call can finish before an earlier one, so ``started_at`` is not an
    identity or completion order. The nested ``MAX(id)`` is the prior
    shape: if that row is still open, this is its start; if it has
    already completed, an older open row does not count.

    The expression is prefixed with a comma for splicing into a select
    list, and degrades to a constant absence on a fixture with no
    ``session_tool_calls`` table, matching this module's schema-tolerance
    contract.
    """
    if not has_session_tool_calls_table(conn):
        return f",NULL AS {OPEN_TOOL_CALL_COLUMN}"
    return open_tool_call_expression(
        session_alias=session_alias, parent_only=_child_marked(conn)
    )


def open_tool_call_expression(*, session_alias: str, parent_only: bool = True) -> str:
    """The open-call select fragment for readers requiring the converged schema.

    Unlike the fixture-tolerant wrapper, this performs no schema read, keeping
    a holder read to one statement while sharing the latest-call semantics.
    Only the parent's own calls count; ``parent_only=False`` is for a schema
    that has not converged the ``agent_type`` marker.
    """
    parent = _parent_rows("tc2") if parent_only else ""
    return (
        ",(SELECT tc.started_at FROM session_tool_calls tc "
        f"WHERE tc.session_id={session_alias}.session_id "
        "AND tc.completed_at IS NULL "
        "AND tc.id=(SELECT MAX(tc2.id) FROM session_tool_calls tc2 "
        f"WHERE tc2.session_id={session_alias}.session_id{parent})) "
        f"AS {OPEN_TOOL_CALL_COLUMN}"
    )


def child_activity_select(conn: Any, *, session_alias: str) -> str:
    """Project the subagent work running since the parent's own last call.

    The run is every child row newer (by ``id``) than the parent's newest
    row, so a parent that ended its turn after starting a background agent
    reads as idle with that agent working since its first call.
    """
    if not has_session_tool_calls_table(conn) or not _child_marked(conn):
        return (
            f",NULL AS {CHILD_AGENT_TYPE_COLUMN},NULL AS {CHILD_ACTIVITY_SINCE_COLUMN}"
            f",NULL AS {OPEN_CHILD_CALL_COLUMN}"
        )
    s = session_alias
    newest_child = (
        "(SELECT MAX(c2.id) FROM session_tool_calls c2 "
        f"WHERE c2.session_id={s}.session_id AND c2.agent_type IS NOT NULL)"
    )
    newest_parent = (
        "COALESCE((SELECT MAX(p.id) FROM session_tool_calls p "
        f"WHERE p.session_id={s}.session_id AND p.agent_type IS NULL), 0)"
    )
    return (
        f",(SELECT c.agent_type FROM session_tool_calls c WHERE c.id={newest_child} "
        f"AND c.id>{newest_parent}) AS {CHILD_AGENT_TYPE_COLUMN}"
        ",(SELECT MIN(c.started_at) FROM session_tool_calls c "
        f"WHERE c.session_id={s}.session_id AND c.agent_type IS NOT NULL "
        f"AND c.id>{newest_parent}) AS {CHILD_ACTIVITY_SINCE_COLUMN}"
        f",(SELECT c.started_at FROM session_tool_calls c WHERE c.id={newest_child} "
        f"AND c.completed_at IS NULL) AS {OPEN_CHILD_CALL_COLUMN}"
    )


def latest_tool_call_select(conn: Any, *, session_alias: str) -> str:
    """Project the latest recorded call start, including completed calls."""
    if not has_session_tool_calls_table(conn):
        return ",NULL AS latest_tool_call_started_at"
    parent = _parent_rows("tc") if _child_marked(conn) else ""
    return (
        ",(SELECT MAX(tc.started_at) FROM session_tool_calls tc "
        f"WHERE tc.session_id={session_alias}.session_id{parent}) "
        "AS latest_tool_call_started_at"
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
    pointed at the state that owns it. Last finished means latest
    ``completed_at``, then highest ``id`` when two completions share a
    stamp: overlapping calls can finish out of start order, and a
    start-time walk would name the wrong tool.

    The expression is prefixed with a comma for splicing into a select
    list, and degrades to a constant absence on a fixture with no
    ``session_tool_calls`` table, matching this module's schema-tolerance
    contract.
    """
    if not has_session_tool_calls_table(conn):
        return f",NULL AS {LAST_COMPLETED_TOOL_COLUMN}"
    parent = _parent_rows("tc") if _child_marked(conn) else ""
    return (
        ",(SELECT tc.tool_name FROM session_tool_calls tc "
        f"WHERE tc.session_id={session_alias}.session_id{parent} "
        "AND tc.completed_at IS NOT NULL "
        "AND tc.tool_name IS NOT NULL AND tc.tool_name <> '' "
        "ORDER BY tc.completed_at DESC, tc.id DESC LIMIT 1) "
        f"AS {LAST_COMPLETED_TOOL_COLUMN}"
    )


__all__ = [
    "CHILD_ACTIVITY_SINCE_COLUMN",
    "CHILD_AGENT_TYPE_COLUMN",
    "LAST_COMPLETED_TOOL_COLUMN",
    "OPEN_CHILD_CALL_COLUMN",
    "MONITOR_TOOL_NAME",
    "OPEN_TOOL_CALL_COLUMN",
    "child_activity_select",
    "last_completed_tool_select",
    "latest_tool_call_select",
    "open_tool_call_expression",
    "open_tool_call_select",
]
