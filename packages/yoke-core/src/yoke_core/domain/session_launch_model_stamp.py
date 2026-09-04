"""Stamp a launched session's requested model facts from the launch record.

A launched session cannot always read its own ask. Claude serves a launch
from a pre-warmed process pool, so the process that runs the session was
started before the launch existed and its environment names no model; the
registration envelope arrives with every ``requested_*`` field null while
the launch row beside it holds the exact string the session was launched
with -- the operator's explicit ask, or the default the chosen machine
named for that surface.
Cursor and Codex do export the ask, but a channel that works on two
harnesses and silently loses the fact on the third is not a channel.

The control plane already holds the ask, so it stamps it at the one moment
both facts are in hand: the binding that ties a launch to the session that
registered for it. Client-side detection stays the channel for sessions an
operator started, which have no launch row to read.

Stamping fills gaps and never rewrites: a session that stated its own ask
observed it from inside the process, and
``yoke_core.domain.session_model_columns`` folds the launch's ask in under
the same stamped-once rule every other registration write obeys.
"""

from __future__ import annotations

from typing import Any, List

from yoke_contracts.session_model_facts import SessionModelFacts

from yoke_core.domain.session_launch_types import LaunchRecord
from yoke_core.domain.session_model_columns import MODEL_COLUMNS, changed_columns
from yoke_core.domain.session_launch_store import marker


def launch_requested_facts(launch: LaunchRecord) -> SessionModelFacts:
    """Return the effective typed selection the launch carried."""
    return SessionModelFacts(
        requested_model=launch.resolved_model,
        requested_reasoning_effort=launch.resolved_reasoning_effort,
        requested_context_window_tokens=launch.resolved_context_window_tokens,
    )


def stamp_launch_requested_facts(
    conn: Any, *, launch: LaunchRecord, session_id: str
) -> List[str]:
    """Fill the bound session's requested columns from the launch ask.

    Returns the columns actually written, so the binding can record which
    facts the control plane supplied rather than leaving an operator to
    infer it. An empty list is the settled case: the launch asked for
    nothing, or the session already stated everything the launch knows.
    """
    facts = launch_requested_facts(launch)
    if not any(getattr(facts, column) is not None for column in MODEL_COLUMNS):
        return []
    p = marker(conn)
    row = conn.execute(
        "SELECT " + ", ".join(MODEL_COLUMNS) + " FROM harness_sessions "
        f"WHERE session_id = {p}",
        (session_id,),
    ).fetchone()
    if row is None:
        return []
    columns, values = changed_columns(row, facts)
    if not columns:
        return []
    assignments = ", ".join(f"{column} = {p}" for column in columns)
    conn.execute(
        f"UPDATE harness_sessions SET {assignments} WHERE session_id = {p}",
        (*values, session_id),
    )
    return columns


__all__ = ["launch_requested_facts", "stamp_launch_requested_facts"]
