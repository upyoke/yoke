"""Stamp a launched session's requested model facts from the launch record.

A launched session cannot always read its own ask. Claude serves a launch
from a pre-warmed process pool, so the process that runs the session was
started before the launch existed and its environment names no model; the
registration envelope arrives with every ``requested_*`` field null while
the launch row beside it holds the exact string the operator asked for.
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

from yoke_contracts.executor_labels import canonical_harness_id
from yoke_contracts.session_model_facts import (
    SessionModelFacts,
    requested_facts_of,
)

from yoke_core.domain.session_launch_types import LaunchRecord
from yoke_core.domain.session_model_columns import MODEL_COLUMNS, changed_columns
from yoke_core.domain.session_launch_store import marker


def launch_requested_facts(launch: LaunchRecord) -> SessionModelFacts:
    """Return the ask this launch states, as far as its selector spells it.

    The selected surface names the harness family, which is what decides
    whether the model string also carries a reasoning level: Cursor spells
    the effort as the variant name's suffix, and no other family does.
    """
    try:
        harness_id = canonical_harness_id(launch.selected_surface)
    except ValueError:
        # A surface outside the harness vocabulary still asked for a model;
        # only the name-encoded effort reading depends on knowing the family.
        harness_id = ""
    return requested_facts_of(launch.requested_model, harness_id=harness_id)


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
    if facts.requested_model is None:
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
