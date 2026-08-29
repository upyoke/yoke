"""What the scheduler calls runnable and unclaimed, and since when.

The waiting clock is the whole reason this is its own read. "Unstaffed since"
is not the item's age: a claim released two minutes ago restarts the wait,
because a released item is newly available rather than newly neglected.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from yoke_core.domain.item_ref_render import render_item_refs
from yoke_core.domain.scheduler import compute_schedule
from yoke_core.domain.scheduler_types import ClaimState, NextStep
from yoke_core.domain.steering_fleet_report_detectors import age_seconds, marker
from yoke_core.domain.work_claim_targets import scope_int_sql


@dataclass(frozen=True)
class FrontierEntry:
    """Runnable unclaimed step; ``was_owned`` means a claim release put it there."""

    item_id: int
    public_ref: str
    title: str
    next_step: str
    rank: int
    pickable_since: str
    was_owned: bool

    def waiting_seconds(self, now: str) -> int:
        return age_seconds(self.pickable_since, now) or 0


def _pickable_since(conn: Any, item_ids: Sequence[int]) -> dict[int, tuple[str, bool]]:
    """When each item became pickable, and whether a claim release put it there."""
    if not item_ids:
        return {}
    p = marker(conn)
    holes = ", ".join(p for _ in item_ids)
    rows = conn.execute(
        f"""SELECT i.id AS id,
                   i.updated_at AS updated_at,
                   i.created_at AS created_at,
                   MAX(c.released_at) AS released_at
              FROM items i
              LEFT JOIN work_claims c
                ON c.target_kind = 'item'
               AND c.released_at IS NOT NULL
               AND {scope_int_sql(conn, "c.scope", "item_id")} = i.id
             WHERE i.id IN ({holes})
             GROUP BY i.id, i.updated_at, i.created_at""",
        tuple(int(item_id) for item_id in item_ids),
    ).fetchall()
    resolved: dict[int, tuple[str, bool]] = {}
    for row in rows:
        record = dict(row)
        released = str(record.get("released_at") or "")
        stamps = [
            str(record.get(name) or "")
            for name in ("updated_at", "created_at", "released_at")
        ]
        latest = max(stamp for stamp in stamps if stamp)
        resolved[int(record["id"])] = (latest, bool(released) and released == latest)
    return resolved


def scope_candidates(
    conn: Any,
    *,
    project_id: int,
    session_id: str,
) -> tuple[FrontierEntry, ...]:
    """Runnable, unclaimed, dispatchable steps in one steering scope.

    A stale claim is deliberately not a candidate: the work still has a holder
    until the stale-session sweep releases it, and reporting it as available
    invites a second worker onto an item it cannot claim. Frozen and
    operator-blocked items never reach here either -- the frontier composition
    this reads separates them out, which is what makes an operator's
    deliberate hold a flag they set rather than a guess the report makes.
    """
    schedule = compute_schedule(
        conn,
        [int(project_id)],
        session_id=session_id,
        emit_events=False,
    )
    steps = [
        step
        for step in schedule.ranked_steps
        if step.claim_state is ClaimState.UNCLAIMED
        and step.next_step is not NextStep.WAIT
    ]
    refs = render_item_refs(conn, [step.item_id for step in steps])
    pickable = _pickable_since(conn, [step.item_id for step in steps])
    entries = []
    for step in steps:
        since, was_owned = pickable.get(step.item_id, (step.created_at, False))
        entries.append(
            FrontierEntry(
                item_id=step.item_id,
                public_ref=refs.get(step.item_id, str(step.item_id)),
                title=step.title,
                next_step=step.next_step.value,
                rank=step.rank,
                pickable_since=since or step.created_at,
                was_owned=was_owned,
            )
        )
    return tuple(entries)


__all__ = ["FrontierEntry", "scope_candidates"]
