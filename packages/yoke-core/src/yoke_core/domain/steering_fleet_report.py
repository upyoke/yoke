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

from dataclasses import dataclass
from typing import Any, Mapping

from yoke_core.domain.session_launch_capacity import MachineCapacity
from yoke_core.domain.steering_fleet_report_abandoned import AbandonedLaunch
from yoke_core.domain.steering_fleet_report_available import FrontierEntry
from yoke_core.domain.steering_fleet_report_capacity import (
    SessionCount,
    SurfaceReadiness,
)
from yoke_core.domain.steering_fleet_report_dead_waits import DeadWait, dead_waits
from yoke_core.domain.steering_fleet_report_deployment_runs import (
    DeploymentRunProgress,
)
from yoke_core.domain.steering_fleet_report_detectors import (
    UnregisteredLaunch,
    suspected_orphaned_waiters,
)
from yoke_core.domain.steering_fleet_report_landed_open import LandedItem
from yoke_core.domain.steering_fleet_report_fingerprint import report_fingerprint
from yoke_core.domain.steering_fleet_report_holders import ClaimHolder
from yoke_core.domain.steering_fleet_report_in_flight import (
    InFlightCall,
    partition_quiet,
)
from yoke_core.domain.steering_fleet_report_landings import (
    FleetLandingReadback,
    landing_readbacks,
)
from yoke_core.domain.steering_fleet_report_limits import MachinePlanLimit
from yoke_core.domain.steering_fleet_report_native_models import MachineNativeModels
from yoke_core.domain.steering_fleet_report_reads import FleetReportReads
from yoke_core.domain.steering_fleet_report_relay_health import RelayHealthCondition
from yoke_core.domain.steering_fleet_report_scope import (
    members_only,
    seat_members,
    sessions_only,
)
from yoke_core.domain.steering_fleet_report_stranded import StrandedSession
from yoke_core.domain.steering_fleet_report_undelivered import UndeliveredMessages
from yoke_core.domain.steering_fleet_report_vendor_errors import VendorErrorSession
from yoke_core.domain.steering_message_recipients import awaiting_seat_count


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
    undelivered: tuple[UndeliveredMessages, ...]
    unregistered_launches: tuple[UnregisteredLaunch, ...]
    landed_open: tuple[LandedItem, ...]
    dead_waits: tuple[DeadWait, ...]
    launchable: tuple[SurfaceReadiness, ...]
    session_counts: tuple[SessionCount, ...]
    suspected_orphaned_waiters: tuple[ClaimHolder, ...] = ()
    #: Quiet holders inside one long-running call: reported, never an alarm.
    in_flight: tuple[InFlightCall, ...] = ()
    abandoned_launches: tuple[AbandonedLaunch, ...] = ()
    plan_limits: tuple[MachinePlanLimit, ...] = ()
    #: What each machine's surfaces say they can select right now, observed
    #: natively. A seat naming a model reads this rather than a compiled-in
    #: catalog, which cannot know what an account gained or lost today.
    native_models: tuple[MachineNativeModels, ...] = ()
    #: Every connected machine's lanes against its cap, full ones included.
    machine_capacity: tuple[MachineCapacity, ...] = ()
    #: Registered machine names keyed by machine id, so every per-machine row
    #: shows the name its operator gave the box rather than a bare UUID.
    machine_names: tuple[tuple[str, str], ...] = ()
    origin_counts: tuple[tuple[str, int], ...] = ()
    #: Live sessions whose last turn the model provider ended. Every other
    #: detector reads one of these as a worker quietly thinking.
    vendor_errors: tuple[VendorErrorSession, ...] = ()
    #: Live sessions that cannot resume: exhausted meter, rejected
    #: credentials, or a model the surface no longer offers. A wake cannot
    #: return them. A pin that only differs from the preferred default is
    #: not this.
    stranded: tuple[StrandedSession, ...] = ()
    relay_health: tuple[RelayHealthCondition, ...] = ()
    #: Role-addressed messages in this scope that no live seat is acting on.
    #: Unowned work used to be invisible precisely here: a report addressed
    #: to a seat that has ended is not anyone's inbox item until a seat
    #: acquires the scope and drains it.
    messages_awaiting_seat: int = 0
    #: Open landing pull requests, with the queue entry and arming read together.
    landings: tuple[FleetLandingReadback, ...] = ()
    #: Every live deployment run, whether or not anything is wrong with it.
    #: A healthy run in flight is reported without an alarm precisely so a
    #: stalled one is visible as an exception rather than as silence.
    deployment_runs: tuple[DeploymentRunProgress, ...] = ()

    def waited_too_long(self) -> tuple[FrontierEntry, ...]:
        """Available work past the staffing threshold: the alarm, not the list."""
        return tuple(
            entry
            for entry in self.available
            if entry.waiting_seconds(self.composed_at) >= self.staffing_after_seconds
        )

    def undelivered_needing_action(self) -> tuple[UndeliveredMessages, ...]:
        """Undelivered envelopes the seat can actually do something about.

        Most of the section is reported so the seat can see why an envelope
        is waiting, not because it is work. A recipient inside an unreturned
        tool call has a hook coming, and resuming that session would start a
        second turn on the same conversation; a recipient still inside the
        delivery window is simply mid-delivery; a recipient that has ended
        cannot be revived. Counting any of those as actionable would raise
        the alarm for ordinary fleet traffic, which is how a real finding
        gets lost.
        """
        return tuple(entry for entry in self.undelivered if entry.needs_seat_action)

    def vendor_errors_needing_action(self) -> tuple[VendorErrorSession, ...]:
        """Vendor-stopped sessions no further relay poll will pick up.

        A session inside its resume backoff is being handled and reads as
        context; one whose budget is spent, or whose failure no retry can
        move, has nobody coming for it and is the seat's.
        """
        return tuple(entry for entry in self.vendor_errors if entry.seat_owed)

    def landings_needing_action(self) -> tuple[FleetLandingReadback, ...]:
        """Open landing records GitHub is no longer driving or could not read."""
        return tuple(entry for entry in self.landings if entry.needs_action)

    def runs_needing_action(self) -> tuple[DeploymentRunProgress, ...]:
        """Live runs that cannot move without someone deciding something.

        A run still working through its obligations is reported and is not
        this. Only one holding a determinate failing verdict, or one with
        nothing left outstanding and no driver, is owed a decision.
        """
        return tuple(entry for entry in self.deployment_runs if entry.needs_action)

    @property
    def actionable(self) -> bool:
        """True when something in this report needs the steerer to act."""
        return bool(
            self.waited_too_long()
            or self.idle
            or self.undelivered_needing_action()
            or self.unregistered_launches
            or self.abandoned_launches
            or self.landed_open
            or self.suspected_orphaned_waiters
            or self.dead_waits
            or self.vendor_errors_needing_action()
            or self.stranded
            or self.landings_needing_action()
            or self.runs_needing_action()
            or self.relay_health
            or self.messages_awaiting_seat
        )

    def fingerprint(self) -> str:
        """Content identity, blind to ages so the report is not noise."""
        return report_fingerprint(self)


def compose_report(
    conn: Any,
    *,
    project_id: int,
    session_id: str,
    staffing_after_seconds: int,
    idle_after_seconds: int,
    now: str,
    scope: Mapping[str, Any] | None = None,
    reads: FleetReportReads | None = None,
) -> FleetReport:
    """Assemble one steering scope's report from live control-plane state.

    ``scope`` is the seat's own scope object. A seat narrowed to a strategy
    document sees only that document's items, so every item-keyed section is
    filtered to its members. Delivery-plane and machine facts stay
    project-wide: a launch that never bound a session has no item to
    attribute, and machines are shared by every seat on them.

    ``reads`` is the request this report belongs to. A caller composing
    several scopes passes its own, so each project's facts are read once
    for the whole request and every scope narrows the same values; a caller
    composing one scope passes nothing and reads them for itself.
    """
    request = reads if reads is not None else FleetReportReads()
    facts = request.project_facts(
        conn, project_id=project_id, session_id=session_id, now=now
    )
    seat_scope = dict(scope) if scope else {"project_id": int(project_id)}
    members = seat_members(conn, seat_scope)
    holders = members_only(facts.holders, members)
    quiet = tuple(
        holder
        for holder in holders
        if holder.native_process_gone
        or (not holder.parked and holder.idle_seconds >= int(idle_after_seconds))
    )
    split = partition_quiet(conn, quiet=quiet, now=now)
    stranded = facts.stranded
    stranded_ids = {entry.session_id for entry in stranded}
    idle = tuple(
        holder for holder in split.idle if holder.session_id not in stranded_ids
    )
    alive_idle = tuple(
        holder for holder in split.alive_idle if holder.session_id not in stranded_ids
    )
    return FleetReport(
        project_id=int(project_id),
        composed_at=now,
        staffing_after_seconds=int(staffing_after_seconds),
        idle_after_seconds=int(idle_after_seconds),
        available=members_only(facts.available, members),
        holders=holders,
        idle=idle,
        undelivered=sessions_only(
            facts.undelivered,
            session_ids=(holder.session_id for holder in holders),
            members=members,
        ),
        unregistered_launches=facts.unregistered_launches,
        abandoned_launches=facts.abandoned_launches,
        landed_open=members_only(facts.landed_open, members),
        deployment_runs=facts.deployment_runs,
        suspected_orphaned_waiters=suspected_orphaned_waiters(conn, idle=alive_idle),
        in_flight=split.in_flight,
        dead_waits=dead_waits(conn, idle=alive_idle, now=now),
        vendor_errors=facts.vendor_errors,
        stranded=stranded,
        launchable=facts.launchable,
        session_counts=facts.session_counts,
        origin_counts=facts.origin_counts,
        plan_limits=facts.plan_limits,
        native_models=facts.native_models,
        machine_capacity=facts.machine_capacity,
        landings=landing_readbacks(
            conn,
            project_id=project_id,
            members=members,
            in_flight_item_ids=frozenset(
                call.item_id for call in split.in_flight if "merge" in call.command
            ),
            reads=request,
        ),
        machine_names=tuple(sorted(facts.machine_names.items())),
        relay_health=facts.relay_health,
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
    "StrandedSession",
    "VendorErrorSession",
    "compose_report",
]
