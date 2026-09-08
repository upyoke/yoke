"""Give an existing tool-call row the earlier start that arrived after it.

Observations are delivered in bounded batches and retried, so a call's
completion can reach the database before its own opening observation. The
completion has no open row to close, inserts one already closed, and stamps
its own instant into both endpoints; the genuine start then arrives to find
a row that already exists.

Discarding it on that conflict threw away the only captured evidence of when
the call began — nine Read and Grep calls in one session recorded no
measurable duration for exactly that reason. Reconciling instead keeps one
row per call identity and lets the earlier valid start win, so the pair of
endpoints converges on the truth whichever order they arrive in.

This lives apart from :mod:`yoke_core.domain.session_activity_state`, which
owns activity accounting, because a late start is a correction to one row's
start endpoint and never a second occurrence of the call: nothing here bumps
a counter, moves a heartbeat, or reopens finished work.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.observe_timing import arriving_start_supersedes


def adopt_earlier_start(
    conn: Any,
    *,
    placeholder: str,
    session_id: str,
    tool_use_id: str,
    started_at: str,
) -> bool:
    """Move one call's ``started_at`` back to a genuine earlier capture.

    Reports whether the row changed. The lookup is scoped by the call's own
    identity ``(session_id, tool_use_id)`` because a tool-use id is unique
    only within its session, and the update writes ``started_at`` alone —
    ``completed_at`` and ``outcome`` stay exactly as the completion left
    them, so a finished call is corrected rather than reopened.

    A start that does not supersede the stored one writes nothing, which is
    what makes a duplicate or replayed start a no-op: it carries the instant
    it always carried.
    """
    row = conn.execute(
        "SELECT started_at FROM session_tool_calls "
        f"WHERE session_id = {placeholder} AND tool_use_id = {placeholder}",
        (session_id, tool_use_id),
    ).fetchone()
    if row is None or not arriving_start_supersedes(row[0], started_at):
        return False
    conn.execute(
        f"UPDATE session_tool_calls SET started_at = {placeholder} "
        f"WHERE session_id = {placeholder} AND tool_use_id = {placeholder}",
        (started_at, session_id, tool_use_id),
    )
    return True


__all__ = ["adopt_earlier_start"]
