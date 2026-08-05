"""Answer whether a path lies in a worktree lane another session holds.

Write authority asks "is this target mine?". That question cannot
refuse a session that reaches into a lane belonging to somebody else,
because a target outside every one of the caller's own claims is
already the ordinary case for control-plane and free paths. This module
asks the complementary question — "does a *different* live session hold
the lane this target is inside?" — which is the only one whose answer
justifies refusing a write on ownership grounds.

Occupancy is keyed by path rather than by item, because the caller
standing in a directory does not know which item owns it. That is the
whole difficulty: an agent triaging another item's failing gate opens
its worktree by path, and every ownership surface in the system wants
an item id first.

Both the lane path and the claim are read from recorded rows
(``item_worktrees.path`` and ``work_claims``), so the answer is
identical whether it is computed on the machine holding the checkout or
on a server evaluating a relayed hook. See
``session_claimed_worktrees`` for why a checkout-mapping lookup is not
usable here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.lint_session_cwd_path_authority import is_inside


@dataclass(frozen=True)
class LaneOccupant:
    """A live claim held by another session over the lane containing a path.

    ``item_ref`` is the public reference (``prefix-sequence``) when it
    can be resolved, and empty otherwise; callers render the numeric
    ``item_id`` only as a fallback, never as the primary identifier.
    """

    claim_id: int
    session_id: str
    item_id: int
    item_ref: str
    lane_path: str


def occupying_claim(
    conn: Any, *, target: str, session_id: str,
) -> Optional[LaneOccupant]:
    """Return the foreign claim over ``target``'s lane, or ``None``.

    ``None`` means the write is not an ownership violation: the target
    is outside every recorded active lane, or its lane's only live
    claims belong to ``session_id`` itself, or the lane carries no live
    claim at all. A released lane and a released claim are both
    invisible here by construction.

    Degrades to ``None`` when the schema cannot answer — a fixture with
    no lane table, or a connection that raises — because an
    unanswerable ownership question must not become a refusal.
    """
    if not target or not target.strip():
        return None
    for row in _active_lane_claims(conn):
        if row.session_id == session_id:
            continue
        if is_inside(target, row.lane_path):
            return row
    return None


def _active_lane_claims(conn: Any) -> List[LaneOccupant]:
    """Every active lane paired with each live claim over its item.

    An ``epic_task`` claim carries ``epic_id`` where the lane table
    carries ``item_id``, so the join matches on either column. The lane
    set is small (one row per live lane on the machine), so the
    containment test runs in Python over recorded absolute paths rather
    than as a SQL prefix match, which would have to reimplement path
    boundary semantics in every dialect.
    """
    from yoke_core.domain.schema_common import _table_exists

    if not _table_exists(conn, "item_worktrees"):
        return []
    if not _table_exists(conn, "work_claims"):
        return []
    has_items = _table_exists(conn, "items")
    has_projects = _table_exists(conn, "projects")
    ref_select = (
        "p.public_item_prefix, i.project_sequence"
        if has_items and has_projects
        else "NULL, NULL"
    )
    ref_join = (
        " LEFT JOIN items i ON i.id = iw.item_id"
        " LEFT JOIN projects p ON p.id = i.project_id"
        if has_items and has_projects
        else ""
    )
    try:
        rows = conn.execute(
            "SELECT iw.path, iw.item_id, wc.id, wc.session_id, "
            f"{ref_select} "
            "FROM item_worktrees iw "
            "JOIN work_claims wc "
            "  ON (wc.item_id = iw.item_id OR wc.epic_id = iw.item_id) "
            f"{ref_join} "
            "WHERE iw.released_at IS NULL AND wc.released_at IS NULL "
            "ORDER BY iw.id, wc.id",
            (),
        ).fetchall()
    except db_backend.operational_error_types(conn):
        return []

    out: List[LaneOccupant] = []
    for row in rows:
        values = list(row) if not hasattr(row, "keys") else [
            row["path"], row["item_id"], row["id"], row["session_id"],
            row["public_item_prefix"], row["project_sequence"],
        ]
        lane_path = str(values[0] or "").strip()
        claim_session = str(values[3] or "")
        if not lane_path or not claim_session:
            continue
        prefix = str(values[4] or "").strip()
        sequence = values[5]
        ref = f"{prefix}-{int(sequence)}" if prefix and sequence else ""
        out.append(
            LaneOccupant(
                claim_id=int(values[2] or 0),
                session_id=claim_session,
                item_id=int(values[1] or 0),
                item_ref=ref,
                lane_path=lane_path,
            )
        )
    return out


__all__ = ["LaneOccupant", "occupying_claim"]
