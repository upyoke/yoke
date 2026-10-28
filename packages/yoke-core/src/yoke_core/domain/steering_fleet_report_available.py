"""What the scheduler calls staffable and unclaimed, and since when.

The waiting clock is the whole reason this is its own read. "Unstaffed since"
is not the item's age: a claim released two minutes ago restarts the wait,
because a released item is newly available rather than newly neglected.

A launch already in ``assigned``, ``launching``, or ``awaiting_registration``
is still a candidate — hiding it would stall a frozen worker — but its clock
runs from that launch, not from when the item became pickable.
"""

from __future__ import annotations

from yoke_contracts.project_contract.project_keys import (
    DEFAULT_STEERING_REPORT_STAFFING_MINUTES,
)
from yoke_core.domain.project_policy_capabilities import project_policy_value
from yoke_core.domain.steering_fleet_report_detectors import parse_stamp

from datetime import datetime

from dataclasses import dataclass
from typing import Any, Sequence

from yoke_core.domain.frontier_landing_wait import landing_wait_reason
from yoke_core.domain.item_ref_render import render_item_refs
from yoke_core.domain.scheduler import compute_schedule
from yoke_core.domain.session_launch_assignment import assignment_ref
from yoke_core.domain.scheduler_types import ClaimState
from yoke_core.domain.steering_fleet_report_detectors import age_seconds, marker
from yoke_core.domain.work_claim_targets import scope_int_sql

#: Launch states that mean a worker is already being staffed onto the item.
STAFFING_LAUNCH_STATES = ("assigned", "launching", "awaiting_registration")


@dataclass(frozen=True)
class FrontierEntry:
    """Runnable unclaimed step; ``was_owned`` means a claim release put it there."""

    item_id: int
    public_ref: str
    title: str
    next_step: str
    rank: int
    pickable_since: datetime | None
    was_owned: bool
    launch_id: str = ""
    launch_state: str = ""
    launched_at: datetime | None = None

    def waiting_seconds(self, now: str) -> int:
        return age_seconds(self.launched_at or self.pickable_since, now) or 0


@dataclass(frozen=True)
class LandingWait:
    """Unclaimed committed work waiting only for its blockers to land."""

    item_id: int
    public_ref: str
    title: str
    reason: str


@dataclass(frozen=True)
class ScopeWork:
    """One schedule pass: what to staff, and committed work that must wait."""

    available: tuple[FrontierEntry, ...]
    landing_waits: tuple[LandingWait, ...]


@dataclass(frozen=True)
class StaffingClock:
    """Pickable instant, in-flight launch, and the report's staffing threshold."""

    pickable_since: datetime | None
    launch_state: str
    staffing_after_seconds: int


def is_unstaffed_ready(
    launch_state: str, waiting_seconds: int, staffing_after_seconds: int
) -> bool:
    """Whether ``FleetReport.waited_too_long`` would include this available row.

    A launch already in flight keeps its own clock on the list and is not
    this alarm. The comparison is the report's seconds threshold.
    """
    return not launch_state and waiting_seconds >= int(staffing_after_seconds)


def _staffing_after_seconds(conn: Any, project_id: int) -> int:
    """The report's overdue bound, in seconds, for one project."""
    try:
        minutes = int(
            project_policy_value(
                conn,
                project_id,
                "steering_report_staffing_minutes",
                DEFAULT_STEERING_REPORT_STAFFING_MINUTES,
            )
        )
    except (TypeError, ValueError):
        minutes = DEFAULT_STEERING_REPORT_STAFFING_MINUTES
    return 60 * max(1, minutes)


def staffing_clocks(
    conn: Any, *, project_id: int, item_ids: Sequence[int]
) -> dict[int, StaffingClock]:
    """Clocks for one project's runnable steps, keyed by internal item id.

    Same pickable instant and in-flight launch read as ``scope_work``,
    plus the staffing threshold the report's overdue mark uses.
    """
    if not item_ids:
        return {}
    refs = render_item_refs(conn, list(item_ids))
    pickable = _pickable_since(conn, item_ids)
    launches = _staffing_launches(conn, project_id)
    threshold = _staffing_after_seconds(conn, project_id)
    clocks: dict[int, StaffingClock] = {}
    for item_id in item_ids:
        public_ref = refs.get(int(item_id), str(item_id))
        since, _was_owned = pickable.get(int(item_id), (None, False))
        _launch_id, launch_state, _launched_at = launches.get(
            public_ref, ("", "", None)
        )
        clocks[int(item_id)] = StaffingClock(
            pickable_since=since,
            launch_state=launch_state,
            staffing_after_seconds=threshold,
        )
    return clocks


def _staffing_launches(
    conn: Any, project_id: int
) -> dict[str, tuple[str, str, datetime | None]]:
    """Earliest in-flight launch keyed by the assignment item ref."""
    p = marker(conn)
    holes = ", ".join(p for _ in STAFFING_LAUNCH_STATES)
    rows = conn.execute(
        f"""SELECT launch_id, state, created_at, session_name
              FROM session_launches
             WHERE project_id = {p}
               AND state IN ({holes})
             ORDER BY created_at ASC, launch_id ASC""",
        (int(project_id), *STAFFING_LAUNCH_STATES),
    ).fetchall()
    assigned: dict[str, tuple[str, str, datetime | None]] = {}
    for row in rows:
        record = dict(row)
        ref = assignment_ref(record.get("session_name"))
        if not ref or ref in assigned:
            continue
        assigned[ref] = (
            str(record["launch_id"]),
            str(record["state"]),
            parse_stamp(record["created_at"]),
        )
    return assigned


def _pickable_since(
    conn: Any, item_ids: Sequence[int]
) -> dict[int, tuple[datetime | None, bool]]:
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
    resolved: dict[int, tuple[datetime | None, bool]] = {}
    for row in rows:
        record = dict(row)
        released = parse_stamp(record.get("released_at"))
        stamps = [
            parse_stamp(record.get(name))
            for name in ("updated_at", "created_at", "released_at")
        ]
        latest = max((stamp for stamp in stamps if stamp is not None), default=None)
        resolved[int(record["id"])] = (latest, bool(released) and released == latest)
    return resolved


def scope_work(
    conn: Any,
    *,
    project_id: int,
    session_id: str,
) -> ScopeWork:
    """Unclaimed steps in one steering scope a new worker could advance, and
    the unclaimed committed work the schedule holds back until its blockers
    land (:mod:`yoke_core.domain.frontier_landing_wait`).

    Staffable is the scheduler's own answer (:mod:`scheduler_staffable`), the
    one its selected step comes from: a landed item waiting on its release or
    close-out, conduct past the WIP cap, and an epic whose task a live session
    holds are not offered here.

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
        for step in schedule.staffable_steps
        if step.claim_state is ClaimState.UNCLAIMED
    ]
    refs = render_item_refs(conn, [step.item_id for step in steps])
    pickable = _pickable_since(conn, [step.item_id for step in steps])
    launches = _staffing_launches(conn, project_id)
    entries = []
    for step in steps:
        since, was_owned = pickable.get(step.item_id, (step.created_at, False))
        public_ref = refs.get(step.item_id, str(step.item_id))
        launch_id, launch_state, launched_at = launches.get(public_ref, ("", "", None))
        entries.append(
            FrontierEntry(
                item_id=step.item_id,
                public_ref=public_ref,
                title=step.title,
                next_step=step.next_step.value,
                rank=step.rank,
                pickable_since=since
                if since is not None
                else parse_stamp(step.created_at),
                was_owned=was_owned,
                launch_id=launch_id,
                launch_state=launch_state,
                launched_at=launched_at,
            )
        )
    return ScopeWork(tuple(entries), _landing_waits(conn, schedule.blocked_steps))


def _landing_waits(conn: Any, blocked: Sequence[Any]) -> tuple[LandingWait, ...]:
    """Blocked steps held only by edges past activation: landing waits.

    The schedule holds an item on a later gate for one reason alone, committed
    work whose blockers have not landed, so those edges are the whole wait.
    """
    steps = [
        step
        for step in blocked
        if step.claim_state is ClaimState.UNCLAIMED
        and step.gate_evaluations
        and all(gate.gate_point != "activation" for gate in step.gate_evaluations)
    ]
    refs = render_item_refs(conn, [step.item_id for step in steps])
    return tuple(
        LandingWait(
            item_id=step.item_id,
            public_ref=refs.get(step.item_id, str(step.item_id)),
            title=step.title,
            reason=landing_wait_reason(
                (gate.blocking_item, gate.satisfaction)
                for gate in step.gate_evaluations
            ),
        )
        for step in steps
    )


__all__ = [
    "FrontierEntry",
    "LandingWait",
    "STAFFING_LAUNCH_STATES",
    "ScopeWork",
    "StaffingClock",
    "is_unstaffed_ready",
    "scope_work",
    "staffing_clocks",
]
