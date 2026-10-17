"""Committed work waiting only for its blockers to land.

Readiness gates on ``activation`` edges alone: an ``integration`` edge holds
back a merge, not a start, so an item behind one is free to build. Once its
lane has committed work, though, building is done and landing is all that is
left — and landing is exactly what the edge holds back. Offering that item as
ready invites a worker who can do nothing but wait, so it waits instead,
naming each blocker and what the blocker still has to do.

A lane has committed work when its active implementation lane records a
commit (``item_worktrees.commit_sha``, written by the post-commit snapshot).

This one rule and its sentence feed every surface that says what is ready:
the Frontier computation the scheduler, ``frontier.list`` (the web Frontier
and ``yoke frontier``) and the steering report's available work all read.
"""

from __future__ import annotations

from typing import Any, Iterable, Set

from yoke_contracts.public_ref import parse_public_item_ref
from yoke_core.domain import db_backend


def _condition_verb(satisfaction: str) -> str:
    """What the blocker still has to do, as a bare verb phrase."""
    if satisfaction == "fact:merged":
        return "merge"
    if satisfaction == "status:done":
        return "be done"
    if satisfaction.startswith("status:"):
        return f"reach {satisfaction[len('status:') :]}"
    if satisfaction.startswith("fact:deployed:"):
        return f"be live on {satisfaction[len('fact:deployed:') :]}"
    return f"satisfy {satisfaction}"


def landing_wait_reason(blockers: Iterable[tuple[str, str]]) -> str:
    """``Waiting on PREFIX-1, PREFIX-2 to merge``, one clause per condition.

    ``blockers`` is each unmet edge's (blocking item, satisfaction) pair.
    """
    grouped: dict[str, list[str]] = {}
    ordered = sorted(
        blockers, key=lambda pair: (parse_public_item_ref(pair[0]), pair[1])
    )
    for blocking_item, satisfaction in ordered:
        refs = grouped.setdefault(_condition_verb(str(satisfaction)), [])
        if blocking_item not in refs:
            refs.append(str(blocking_item))
    clauses = [f"{', '.join(refs)} to {verb}" for verb, refs in grouped.items()]
    return "Waiting on " + " and ".join(clauses)


def committed_lane_item_ids(conn: Any, item_ids: Iterable[int]) -> Set[int]:
    """Items among ``item_ids`` whose active implementation lane has a commit."""
    ids = sorted({int(value) for value in item_ids})
    if not ids:
        return set()
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    rows = conn.execute(
        "SELECT DISTINCT item_id FROM item_worktrees "
        "WHERE state = 'active' AND lane_role = 'implementation' "
        "AND commit_sha IS NOT NULL AND commit_sha <> '' "
        f"AND item_id IN ({', '.join(marker for _ in ids)})",
        tuple(ids),
    ).fetchall()
    return {int(dict(row)["item_id"]) for row in rows}


__all__ = ["committed_lane_item_ids", "landing_wait_reason"]
