"""What the steering seat cannot see from inside its own turn.

A steering session spends its attention on whatever it is currently doing,
and the fleet keeps changing underneath it: an item becomes runnable and
nobody picks it up, a worker's claim is released by a liveness sweep and the
item quietly stops moving, a claim-holder goes silent. None of those announce
themselves. The only detector used to be the steerer's own memory to go and
look, which is a habit rather than a guarantee — three runnable items once sat
unstaffed while the steerer worked on something else.

This module composes that negative space into one report. It decides nothing
and launches nothing: staffing is the steerer's judgment, and a report that
hires workers is the system this one replaced.

Every detector here is a **time threshold**, never an instantaneous read.
Each lifecycle segment boundary releases a claim and reacquires moments
later, so a zero-owner snapshot is the normal shape of healthy work — a
sweep that read that window as abandonment once staffed a duplicate worker
onto a live item. A parked session is also a separate fact from an unowned
item: a session that stamped ``parked`` declared its wait, and folding the
two into one alarm teaches the steerer to skim.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Sequence

from yoke_contracts.executor_labels import KNOWN_SURFACE_LABELS
from yoke_contracts.session_control.capabilities import capability_for_surface
from yoke_core.domain import db_backend
from yoke_core.domain.item_ref_render import render_item_refs
from yoke_core.domain.scheduler import compute_schedule
from yoke_core.domain.scheduler_types import ClaimState, NextStep
from yoke_core.domain.session_launch_eligibility import derive_launch_eligibility


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _scope_item_id(conn: Any, column: str = "c.scope") -> str:
    from yoke_core.domain.work_claim_targets import scope_int_sql

    return scope_int_sql(conn, column, "item_id")


def _parse(raw: str) -> datetime:
    parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _age_seconds(stamp: str | None, now: str) -> int | None:
    if not stamp:
        return None
    return max(0, int((_parse(now) - _parse(stamp)).total_seconds()))


@dataclass(frozen=True)
class FrontierEntry:
    """One runnable, unclaimed, non-waiting step in a steering scope.

    ``pickable_since`` is when the work became available — the later of its
    own last change and the last release of a claim on it — so its age reads
    "how long has this sat there", not "how old is the item". ``was_owned``
    records which of those two won: work whose clock restarted at a claim
    release stopped, while work that never carried a claim never started.
    """

    item_id: int
    item_ref: str
    title: str
    next_step: str
    rank: int
    pickable_since: str
    was_owned: bool

    def waiting_seconds(self, now: str) -> int:
        return _age_seconds(self.pickable_since, now) or 0


@dataclass(frozen=True)
class ClaimHolder:
    """One live session holding one item's work claim."""

    session_id: str
    item_id: int
    item_ref: str
    mode: str
    parked: bool
    last_activity_at: str
    idle_seconds: int


@dataclass(frozen=True)
class SurfaceReadiness:
    """One ``(machine, surface)`` pair a launch could reach right now."""

    machine_id: str
    surface: str


@dataclass(frozen=True)
class FleetReport:
    """One steering scope's unowned, idle, and available work."""

    project_id: int
    composed_at: str
    stale_after_seconds: int
    frontier: tuple[FrontierEntry, ...]
    unstaffed: tuple[FrontierEntry, ...]
    unowned: tuple[FrontierEntry, ...]
    holders: tuple[ClaimHolder, ...]
    idle: tuple[ClaimHolder, ...]
    launchable: tuple[SurfaceReadiness, ...]

    @property
    def actionable(self) -> bool:
        """True when something in this report needs the steerer to act."""
        return bool(self.unstaffed or self.unowned or self.idle)

    def fingerprint(self) -> str:
        """Identity of the report's content, blind to how old anything is.

        Ages advance every second; including them would make every report
        "changed" and defeat the suppression that keeps this from becoming
        noise the steerer learns to skim.
        """
        material = {
            "frontier": sorted(entry.item_id for entry in self.frontier),
            "unstaffed": sorted(entry.item_id for entry in self.unstaffed),
            "unowned": sorted(entry.item_id for entry in self.unowned),
            "holders": sorted(
                (holder.session_id, holder.item_id) for holder in self.holders
            ),
            "idle": sorted(
                (holder.session_id, holder.item_id) for holder in self.idle
            ),
            "launchable": sorted(
                (ready.machine_id, ready.surface) for ready in self.launchable
            ),
        }
        encoded = json.dumps(material, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _pickable_since(conn: Any, item_ids: Sequence[int]) -> dict[int, tuple[str, bool]]:
    """When each item became pickable, and whether a claim release put it there."""
    if not item_ids:
        return {}
    marker = _p(conn)
    holes = ", ".join(marker for _ in item_ids)
    rows = conn.execute(
        f"""SELECT i.id AS id,
                   i.updated_at AS updated_at,
                   i.created_at AS created_at,
                   MAX(c.released_at) AS released_at
              FROM items i
              LEFT JOIN work_claims c
                ON c.target_kind = 'item'
               AND c.released_at IS NOT NULL
               AND {_scope_item_id(conn)} = i.id
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

    A stale claim is deliberately not a candidate: the work still has a
    holder until the stale-session sweep releases it, and reporting it as
    available invites a second worker onto an item it cannot claim.
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
                item_ref=refs.get(step.item_id, str(step.item_id)),
                title=step.title,
                next_step=step.next_step.value,
                rank=step.rank,
                pickable_since=since or step.created_at,
                was_owned=was_owned,
            )
        )
    return tuple(entries)


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
                item_ref=refs.get(int(record["item_id"]), str(record["item_id"])),
                mode=mode,
                parked=mode == "parked",
                last_activity_at=last_activity,
                idle_seconds=_age_seconds(last_activity, now) or 0,
            )
        )
    return tuple(holders)


def launchable_surfaces(
    conn: Any,
    *,
    project_id: int,
    now: str,
) -> tuple[SurfaceReadiness, ...]:
    """Every ``(machine, surface)`` a launch could reach for this project.

    Read through the same eligibility composition the launch preview uses, so
    the report can never claim a surface the launch plane would refuse.
    """
    ready: set[tuple[str, str]] = set()
    for surface in KNOWN_SURFACE_LABELS:
        capability = capability_for_surface(surface)
        if capability is None or capability.create == "none":
            continue
        snapshot = derive_launch_eligibility(
            conn,
            project_id=int(project_id),
            surface=surface,
            machine_id=None,
            now=now,
        )
        for relay in snapshot.relays:
            ready.add((relay.machine_id, surface))
    return tuple(
        SurfaceReadiness(machine_id=machine, surface=surface)
        for machine, surface in sorted(ready)
    )


def compose_report(
    conn: Any,
    *,
    project_id: int,
    session_id: str,
    stale_after_seconds: int,
    now: str,
) -> FleetReport:
    """Assemble one steering scope's report from live control-plane state."""
    frontier = scope_candidates(conn, project_id=project_id, session_id=session_id)
    stale = int(stale_after_seconds)
    aged = [entry for entry in frontier if entry.waiting_seconds(now) >= stale]
    holders = claim_holders(conn, project_id=project_id, now=now)
    return FleetReport(
        project_id=int(project_id),
        composed_at=now,
        stale_after_seconds=stale,
        frontier=frontier,
        unstaffed=tuple(entry for entry in aged if not entry.was_owned),
        unowned=tuple(entry for entry in aged if entry.was_owned),
        holders=holders,
        idle=tuple(
            holder
            for holder in holders
            if not holder.parked and holder.idle_seconds >= stale
        ),
        launchable=launchable_surfaces(conn, project_id=project_id, now=now),
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
