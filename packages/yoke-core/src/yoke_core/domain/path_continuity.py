"""Path continuity recording (path continuity layer ``path_moves`` writers).

A ``path_moves`` row is an *authored* statement that one canonical path
target is the conceptual successor of another. Continuity is workflow
or operator truth; the writer refuses heuristic-only signal. Git
similarity output is not accepted as recording authority.

Two distinct authoring paths are exposed; both land rows in the same
table but the provenance event distinguishes how the record was
authorized:

* :func:`record_workflow_observed_move` - a Yoke workflow observed
  the transition inside its own surface (e.g. a coordinated rename
  through Yoke-managed tooling). The caller supplies the event id
  the workflow already emitted to mark the observation.
* :func:`record_operator_adjudicated_move` - an operator declared an
  after-the-fact continuity edge. The caller supplies the event id of
  the operator-authored event that adjudicated the link.

Both writers require a non-empty ``recorded_event_id`` provenance
string. The string is opaque — it is NOT verified against the events
ledger, because severity retention prunes ledger rows on a schedule
the durable continuity rows outlive (decision record:
``docs/archive/decisions/path-provenance-event-fk.md``). Continuity
reads return ``continuity_unknown`` (a read-side sentinel) when
descendant projection cannot resolve a fact; the sentinel is **not**
persisted.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import iso8601_now


CONTINUITY_UNKNOWN = "continuity_unknown"


class PathContinuityError(Exception):
    """Raised when continuity authoring cannot proceed."""


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _verify_provenance_string(event_id: Any) -> None:
    if not isinstance(event_id, str) or not event_id.strip():
        raise PathContinuityError(
            "recorded_event_id must be a non-empty provenance string; "
            "continuity authoring requires a recorded provenance event id"
        )


def _verify_target_exists(
    conn: Any, target_id: int, role: str,
) -> None:
    row = conn.execute(
        f"SELECT 1 FROM path_targets WHERE id = {_p(conn)}", (target_id,),
    ).fetchone()
    if row is None:
        raise PathContinuityError(
            f"{role}_target_id={target_id} not found in path_targets"
        )


def _verify_distinct(before_id: int, after_id: int) -> None:
    if before_id == after_id:
        raise PathContinuityError(
            f"path_moves requires distinct before/after target ids "
            f"(both were {before_id}); a move connects two identities"
        )


def _record_move(
    conn: Any,
    *,
    before_target_id: int,
    after_target_id: int,
    recorded_event_id: str,
) -> int:
    _verify_distinct(before_target_id, after_target_id)
    _verify_target_exists(conn, before_target_id, role="before")
    _verify_target_exists(conn, after_target_id, role="after")
    _verify_provenance_string(recorded_event_id)
    cur = conn.execute(
        "INSERT INTO path_moves "
        "(before_target_id, after_target_id, recorded_event_id, recorded_at) "
        f"VALUES ({_p(conn)}, {_p(conn)}, {_p(conn)}, {_p(conn)}) RETURNING id",
        (before_target_id, after_target_id, recorded_event_id, iso8601_now()),
    )
    return int(cur.fetchone()[0])


def record_workflow_observed_move(
    conn: Any,
    *,
    before_target_id: int,
    after_target_id: int,
    recorded_event_id: str,
) -> int:
    """Record a continuity edge observed inside a Yoke workflow.

    The caller MUST have emitted the provenance event before calling.
    The ``recorded_event_id`` is stored as an opaque provenance string
    (not verified against the retention-pruned ledger); the envelope is
    expected to mark the record as workflow-observed (the table itself
    does not enforce that; the event registry and consumers do).

    Heuristic detection is not a workflow observation. Rebinding a
    rename via git similarity output, file-content fingerprinting, or
    any other inferred signal is not an authored continuity edge and
    must not call this writer.

    Returns the new ``path_moves.id``.
    """
    return _record_move(
        conn,
        before_target_id=before_target_id,
        after_target_id=after_target_id,
        recorded_event_id=recorded_event_id,
    )


def record_operator_adjudicated_move(
    conn: Any,
    *,
    before_target_id: int,
    after_target_id: int,
    recorded_event_id: str,
) -> int:
    """Record a continuity edge declared by an operator after the fact.

    Same shape as :func:`record_workflow_observed_move` but with a
    different provenance: the linked event represents the operator's
    explicit adjudication (the envelope distinguishes this branch from
    the workflow-observed branch). The table writer does not enforce
    the source distinction; the event envelope owns it.

    Returns the new ``path_moves.id``.
    """
    return _record_move(
        conn,
        before_target_id=before_target_id,
        after_target_id=after_target_id,
        recorded_event_id=recorded_event_id,
    )


def latest_successor(
    conn: Any, target_id: int,
) -> Optional[int]:
    """Return the after-target of the most recent move out of *target_id*,
    or ``None`` when no move has been recorded.

    Successor lookups walk only one step. Multi-step transitive chains
    are an out-of-scope concern; callers compose if they need them.
    """
    row = conn.execute(
        "SELECT after_target_id FROM path_moves "
        f"WHERE before_target_id = {_p(conn)} "
        "ORDER BY id DESC LIMIT 1",
        (target_id,),
    ).fetchone()
    if row is None:
        return None
    return int(row[0])


__all__ = [
    "CONTINUITY_UNKNOWN",
    "PathContinuityError",
    "latest_successor",
    "record_operator_adjudicated_move",
    "record_workflow_observed_move",
]
