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

Quiet is not the same as stuck
------------------------------
A worker inside one long foreground call records no new tool call while that
call runs, so the quiet threshold alone reads a working merge wait as stuck.
:mod:`steering_fleet_report_in_flight` partitions the quiet holders so the
idle alarm keeps meaning "nobody is driving this".

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
from typing import Any, Mapping

from yoke_contracts.session_holdings import work_holding_key
from yoke_core.domain import db_backend
from yoke_core.domain.session_mode import session_is_parked
from yoke_core.domain.session_native_process_observation import (
    current_native_process_observation,
)
from yoke_core.domain.sessions_holdings_projection import session_holdings_by_session
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
from yoke_core.domain.steering_fleet_report_in_flight import (
    InFlightCall,
    partition_quiet,
)
from yoke_core.domain.steering_fleet_report_starvation import (
    StarvedDelivery,
    starved_deliveries,
)
from yoke_core.domain.steering_fleet_report_abandoned import (
    AbandonedLaunch,
    abandoned_launches,
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
from yoke_core.domain.steering_fleet_report_scope import (
    members_only,
    seat_members,
    sessions_only,
)
from yoke_core.domain.steering_fleet_report_limits import (
    MachinePlanLimit,
    fingerprint_material,
    load_plan_limits,
)


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


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
    native_process_gone_at: str = ""

    @property
    def native_process_gone(self) -> bool:
        return bool(self.native_process_gone_at)


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
    #: Quiet holders inside one long-running call: reported, never an alarm.
    in_flight: tuple[InFlightCall, ...] = ()
    abandoned_launches: tuple[AbandonedLaunch, ...] = ()
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
            or self.abandoned_launches
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
                (holder.session_id, holder.item_id, holder.native_process_gone)
                for holder in self.holders
            ),
            "idle": sorted((holder.session_id, holder.item_id) for holder in self.idle),
            "starved": sorted(entry.session_id for entry in self.starved),
            "unregistered_launches": sorted(
                (entry.launch_id, entry.native_launch_phase, entry.spawn_duration_ms)
                for entry in self.unregistered_launches
            ),
            "abandoned_launches": sorted(
                entry.launch_id for entry in self.abandoned_launches
            ),
            "landed_open": sorted(entry.item_id for entry in self.landed_open),
            "suspected_orphaned_waiters": sorted(
                (holder.session_id, holder.item_id)
                for holder in self.suspected_orphaned_waiters
            ),
            "in_flight": sorted((c.session_id, c.command) for c in self.in_flight),
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
    holdings = session_holdings_by_session(conn, previous_limit=0)
    item_prefix = work_holding_key("item", item_id="")
    candidates = []
    for session_id, grouped in holdings.items():
        for entry in grouped.get("current") or []:
            target_key = str(entry.get("target_key") or "")
            if (
                entry.get("holding_kind") != "work_claim"
                or entry.get("target_kind") != "item"
                or int(entry.get("item_project_id") or 0) != int(project_id)
                or not target_key.startswith(item_prefix)
            ):
                continue
            item_id = target_key.removeprefix(item_prefix)
            if item_id.isdigit():
                candidates.append((session_id, int(item_id), entry))
    if not candidates:
        return ()
    marker = _p(conn)
    session_ids = sorted({session_id for session_id, _item_id, _entry in candidates})
    placeholders = ",".join(marker for _ in session_ids)
    rows = conn.execute(
        "SELECT session_id,mode,last_tool_call_at,last_heartbeat,episode_started_at,"
        "native_process_gone_at,native_process_gone_evidence "
        "FROM harness_sessions "
        f"WHERE session_id IN ({placeholders}) AND ended_at IS NULL "
        "AND terminated_at IS NULL",
        tuple(session_ids),
    ).fetchall()
    sessions = {str(row["session_id"]): dict(row) for row in rows}
    holders = []
    for session_id, item_id, entry in sorted(
        candidates, key=lambda value: (str(value[2].get("claimed_at") or ""), value[1])
    ):
        record = sessions.get(session_id)
        if record is None:
            continue
        last_activity = str(
            record.get("last_tool_call_at") or entry.get("claimed_at") or ""
        )
        mode = str(record.get("mode") or "")
        process = current_native_process_observation(record) or {}
        holders.append(
            ClaimHolder(
                session_id=session_id,
                item_id=item_id,
                public_ref=str(
                    entry.get("public_ref") or entry.get("target") or item_id
                ),
                mode=mode,
                parked=session_is_parked(mode),
                last_activity_at=last_activity,
                idle_seconds=age_seconds(last_activity, now) or 0,
                native_process_gone_at=str(process.get("observed_at") or ""),
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
    scope: Mapping[str, Any] | None = None,
) -> FleetReport:
    """Assemble one steering scope's report from live control-plane state.

    ``scope`` is the seat's own scope object. A seat narrowed to a strategy
    document sees only that document's items, so every item-keyed section is
    filtered to its members. Delivery-plane and machine facts stay
    project-wide: a launch that never bound a session has no item to
    attribute, and machines are shared by every seat on them.
    """
    seat_scope = dict(scope) if scope else {"project_id": int(project_id)}
    members = seat_members(conn, seat_scope)
    holders = members_only(
        claim_holders(conn, project_id=project_id, now=now), members
    )
    quiet = tuple(
        holder
        for holder in holders
        if holder.native_process_gone
        or (not holder.parked and holder.idle_seconds >= int(idle_after_seconds))
    )
    split = partition_quiet(conn, quiet=quiet, now=now)
    alive_idle = split.alive_idle
    return FleetReport(
        project_id=int(project_id),
        composed_at=now,
        staffing_after_seconds=int(staffing_after_seconds),
        idle_after_seconds=int(idle_after_seconds),
        available=members_only(
            scope_candidates(conn, project_id=project_id, session_id=session_id),
            members,
        ),
        holders=holders,
        idle=split.idle,
        starved=sessions_only(
            starved_deliveries(conn, project_id=project_id, now=now),
            session_ids=(holder.session_id for holder in holders),
            members=members,
        ),
        unregistered_launches=unregistered_launches(
            conn, project_id=project_id, now=now
        ),
        abandoned_launches=abandoned_launches(conn, project_id=project_id, now=now),
        landed_open=members_only(
            landed_without_closeout(conn, project_id=project_id, now=now), members
        ),
        suspected_orphaned_waiters=suspected_orphaned_waiters(conn, idle=alive_idle),
        in_flight=split.in_flight,
        dead_waits=dead_waits(conn, idle=alive_idle, now=now),
        launchable=launchable_surfaces(conn, project_id=project_id, now=now),
        session_counts=live_session_counts(conn, project_id=project_id),
        origin_counts=live_launch_origin_counts(conn, project_id=project_id),
        plan_limits=load_plan_limits(conn, project_id=project_id, now=now),
        messages_awaiting_seat=awaiting_seat_count(
            conn,
            project_id=int(project_id),
            scope=seat_scope,
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
