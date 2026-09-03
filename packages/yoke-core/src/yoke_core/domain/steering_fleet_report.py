"""What the steering seat cannot see from inside its own turn.

Composes available work, idle holders, five silent failure classes,
launchable surfaces, and live session counts into one report. It decides
nothing and launches nothing. The only detector used to be the steerer's own
memory to go and look, which is a habit rather than a guarantee.

Two thresholds, because two different questions
-----------------------------------------------
``staffing_after_seconds`` answers "how long may runnable work sit unclaimed
before the report calls that a failure rather than an opportunity". For a
seat whose standing instruction is to keep the frontier staffed the honest
answer is nearly zero; it is not zero only because every lifecycle segment
boundary releases a claim and reacquires moments later, and a report that
fires on that window teaches the seat to ignore it.

``idle_after_seconds`` answers "how long must a claim holder be quiet before
it is presumed stuck". That is a judgment about a worker mid-task, not about
a queue, and it is legitimately a longer number. The two shared one value
once; they are unrelated concepts that happened to share a default.

The stale-claim window is already covered
-----------------------------------------
A stale claim is deliberately not a candidate for available work: the item
still has a holder until the stale-session sweep releases it, and reporting
it as available invites a second worker onto an item it cannot claim. That
leaves the window between a holder going stale and the sweep firing -- and
that window is not silent. ``claim_holders`` excludes only ended and
terminated sessions, and idleness is measured from ``last_tool_call_at``
rather than from any liveness label, so a stale-but-unswept holder is in the
idle list from ``idle_after_seconds`` onward and its item moves to available
the moment the sweep releases it. There is no moment when the item is in no
section, so the window gets no line of its own.

A deliberately held item is the operator's flag to set
------------------------------------------------------
An item an operator is holding on purpose would otherwise read as available
forever. The report does not guess at intent: the frontier composition it
reads already drops frozen and operator-blocked items before they reach it,
so ``yoke items freeze`` and ``yoke items block`` are the whole hold
mechanism. Work that will never resume is ``yoke items cancel``, not
freeze. An item that has read "waiting 30h12m" all day is one nobody flagged, and
teaching the report to infer a hold from age would hide real unstaffed work.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.item_ref_render import render_item_refs
from yoke_core.domain.session_mode import session_is_parked
from yoke_core.domain.steering_fleet_report_available import (
    FrontierEntry,
    scope_candidates,
)
from yoke_core.domain.steering_fleet_report_capacity import (
    SurfaceReadiness,
    launchable_surfaces,
    live_launch_origin_counts,
    live_session_counts,
)
from yoke_core.domain.steering_fleet_report_dead_waits import DeadWait, dead_waits
from yoke_core.domain.steering_fleet_report_starvation import (
    StarvedDelivery,
    starved_deliveries,
)
from yoke_core.domain.steering_fleet_report_detectors import (
    LandedItem,
    UnregisteredLaunch,
    age_seconds,
    landed_without_closeout,
    suspected_orphaned_waiters,
    unregistered_launches,
)
from yoke_core.domain.steering_message_recipients import awaiting_seat_count
from yoke_core.domain.steering_fleet_report_limits import (
    MachinePlanLimit,
    fingerprint_material,
    load_plan_limits,
)


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _scope_item_id(conn: Any, column: str = "c.scope") -> str:
    from yoke_core.domain.work_claim_targets import scope_int_sql

    return scope_int_sql(conn, column, "item_id")


@dataclass(frozen=True)
class ClaimHolder:
    """One live session holding one item's work claim."""

    session_id: str
    item_id: int
    public_ref: str
    mode: str
    parked: bool
    last_activity_at: str
    idle_seconds: int


@dataclass(frozen=True)
class FleetReport:
    """One steering scope's available work, quiet workers, and silent failures."""

    project_id: int
    composed_at: str
    staffing_after_seconds: int
    idle_after_seconds: int
    available: tuple[FrontierEntry, ...]
    holders: tuple[ClaimHolder, ...]
    idle: tuple[ClaimHolder, ...]
    starved: tuple[StarvedDelivery, ...]
    unregistered_launches: tuple[UnregisteredLaunch, ...]
    landed_open: tuple[LandedItem, ...]
    dead_waits: tuple[DeadWait, ...]
    launchable: tuple[SurfaceReadiness, ...]
    session_counts: tuple[tuple[str, str, int], ...]
    suspected_orphaned_waiters: tuple[ClaimHolder, ...] = ()
    plan_limits: tuple[MachinePlanLimit, ...] = ()
    origin_counts: tuple[tuple[str, int], ...] = ()
    #: Role-addressed messages in this scope that no live seat is acting on.
    #: Unowned work used to be invisible precisely here: a report addressed
    #: to a seat that has ended is not anyone's inbox item until a seat
    #: acquires the scope and drains it.
    messages_awaiting_seat: int = 0

    def waited_too_long(self) -> tuple[FrontierEntry, ...]:
        """Available work past the staffing threshold: the alarm, not the list."""
        return tuple(
            entry
            for entry in self.available
            if entry.waiting_seconds(self.composed_at) >= self.staffing_after_seconds
        )

    @property
    def actionable(self) -> bool:
        """True when something in this report needs the steerer to act."""
        return bool(
            self.waited_too_long()
            or self.idle
            or self.starved
            or self.unregistered_launches
            or self.landed_open
            or self.suspected_orphaned_waiters
            or self.dead_waits
            or self.messages_awaiting_seat
        )

    def fingerprint(self) -> str:
        """Content identity, blind to ages so the report is not noise."""
        counts = {(machine, surface): n for machine, surface, n in self.session_counts}
        material = {
            "available": sorted(entry.item_id for entry in self.available),
            "holders": sorted(
                (holder.session_id, holder.item_id) for holder in self.holders
            ),
            "idle": sorted((holder.session_id, holder.item_id) for holder in self.idle),
            "starved": sorted(entry.session_id for entry in self.starved),
            "unregistered_launches": sorted(
                (entry.launch_id, entry.native_launch_phase, entry.spawn_duration_ms)
                for entry in self.unregistered_launches
            ),
            "landed_open": sorted(entry.item_id for entry in self.landed_open),
            "suspected_orphaned_waiters": sorted(
                (holder.session_id, holder.item_id)
                for holder in self.suspected_orphaned_waiters
            ),
            "dead_waits": sorted(
                (entry.session_id, entry.answerer_session_id, entry.reason)
                for entry in self.dead_waits
            ),
            "launch_balance": sorted(
                (r.machine_id, r.surface, counts.get((r.machine_id, r.surface), 0))
                for r in self.launchable
            ),
            "plan_limits": fingerprint_material(self.plan_limits),
            "origin_counts": list(self.origin_counts),
            "messages_awaiting_seat": self.messages_awaiting_seat,
        }
        encoded = json.dumps(material, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def claim_holders(
    conn: Any,
    *,
    project_id: int,
    now: str,
) -> tuple[ClaimHolder, ...]:
    """Live sessions holding an item work claim in one project.

    Ended and terminated sessions are excluded: their claims are the
    stale-session sweep's business, and reporting a session that is already
    gone as an idle worker re-fires the same false alarm on every pass.
    """
    item_id = _scope_item_id(conn)
    marker = _p(conn)
    rows = conn.execute(
        f"""SELECT s.session_id AS session_id,
                   s.mode AS mode,
                   s.last_tool_call_at AS last_tool_call_at,
                   s.last_heartbeat AS last_heartbeat,
                   c.claimed_at AS claimed_at,
                   {item_id} AS item_id
              FROM work_claims c
              JOIN harness_sessions s ON s.session_id = c.session_id
              JOIN items i ON i.id = {item_id}
             WHERE c.target_kind = 'item'
               AND c.released_at IS NULL
               AND s.ended_at IS NULL
               AND s.terminated_at IS NULL
               AND i.project_id = {marker}
             ORDER BY c.claimed_at ASC, c.id ASC""",
        (int(project_id),),
    ).fetchall()
    records = [dict(row) for row in rows]
    refs = render_item_refs(conn, [int(record["item_id"]) for record in records])
    holders = []
    for record in records:
        last_activity = str(
            record.get("last_tool_call_at") or record.get("claimed_at") or ""
        )
        mode = str(record.get("mode") or "")
        holders.append(
            ClaimHolder(
                session_id=str(record["session_id"]),
                item_id=int(record["item_id"]),
                public_ref=refs.get(int(record["item_id"]), str(record["item_id"])),
                mode=mode,
                parked=session_is_parked(mode),
                last_activity_at=last_activity,
                idle_seconds=age_seconds(last_activity, now) or 0,
            )
        )
    return tuple(holders)


def compose_report(
    conn: Any,
    *,
    project_id: int,
    session_id: str,
    staffing_after_seconds: int,
    idle_after_seconds: int,
    now: str,
) -> FleetReport:
    """Assemble one steering scope's report from live control-plane state."""
    holders = claim_holders(conn, project_id=project_id, now=now)
    idle = tuple(
        holder
        for holder in holders
        if not holder.parked and holder.idle_seconds >= int(idle_after_seconds)
    )
    return FleetReport(
        project_id=int(project_id),
        composed_at=now,
        staffing_after_seconds=int(staffing_after_seconds),
        idle_after_seconds=int(idle_after_seconds),
        available=scope_candidates(conn, project_id=project_id, session_id=session_id),
        holders=holders,
        idle=idle,
        starved=starved_deliveries(conn, project_id=project_id, now=now),
        unregistered_launches=unregistered_launches(
            conn, project_id=project_id, now=now
        ),
        landed_open=landed_without_closeout(conn, project_id=project_id, now=now),
        suspected_orphaned_waiters=suspected_orphaned_waiters(conn, idle=idle),
        dead_waits=dead_waits(conn, idle=idle, now=now),
        launchable=launchable_surfaces(conn, project_id=project_id, now=now),
        session_counts=live_session_counts(conn, project_id=project_id),
        origin_counts=live_launch_origin_counts(conn, project_id=project_id),
        plan_limits=load_plan_limits(conn, project_id=project_id, now=now),
        messages_awaiting_seat=awaiting_seat_count(
            conn,
            project_id=int(project_id),
            scope={"project_id": int(project_id)},
        ),
    )


__all__ = [
    "ClaimHolder",
    "FleetReport",
    "FrontierEntry",
    "SurfaceReadiness",
    "claim_holders",
    "compose_report",
    "launchable_surfaces",
    "scope_candidates",
]
