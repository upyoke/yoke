"""Place a launch on the machine and surface with the most headroom.

Work goes where capacity is. When a launch names no machine, this module
weighs every machine the requester may use that offers the surface, ranks
them by the lowest plan-limit headroom each publishes for it, and prefers
the requester's own machine when those readings are close enough to be the
same answer -- spending a colleague's quota is a cost the requester did not
choose. The chosen machine and the sentence explaining why are recorded on
the preview and on the launch row, so a seat can read the decision instead of
reconstructing it.

Headroom here is the same reading the fleet report renders: remaining
full-rate runway over time-to-reset, per (machine, surface, window). It ranks
placement; it never refuses one. A fleet whose meters are all unreadable
still places work.
"""

from __future__ import annotations

from typing import Any, Sequence

from yoke_core.domain.session_launch_capacity import MACHINE_AT_CAPACITY
from yoke_core.domain.session_launch_machine_access import machine_access
from yoke_core.domain.session_launch_types import (
    EligibilitySnapshot,
    EligibleRelay,
    LaunchPreview,
    MachineCandidate,
)
from yoke_core.domain.steering_fleet_plan_capacity import (
    compute_plan_limit,
    window_label,
)
from yoke_core.domain.steering_fleet_report_limits import load_plan_limits


# Two readings within this many percentage points answer the same question,
# so ownership -- not a rounding difference -- decides between them.
COMPARABLE_HEADROOM_POINTS = 10.0

ACCESS_DENIED_OUTCOME = "machine_access_denied"


def _percent(value: float | None) -> str:
    return "unreadable" if value is None else f"{int(round(value))}%"


def surface_headroom(
    conn: Any, *, project_id: int, now: str
) -> dict[tuple[str, str], tuple[float, str]]:
    """Return the lowest readable headroom per (machine, surface).

    A surface publishes several meters at once; the one that binds is the one
    with the least headroom, so that is the reading placement compares.
    """
    lowest: dict[tuple[str, str], tuple[float, str]] = {}
    for row in load_plan_limits(conn, project_id=project_id, now=now):
        computed = compute_plan_limit(row, now=now)
        if computed.headroom_percent is None:
            continue
        key = (row.machine_id, row.surface)
        label = window_label(row.window_kind, row.scope)
        current = lowest.get(key)
        if current is None or computed.headroom_percent < current[0]:
            lowest[key] = (computed.headroom_percent, label)
    return lowest


def _candidates(
    conn: Any,
    *,
    relays: Sequence[EligibleRelay],
    actor_id: int,
    project_id: int,
    now: str,
    snapshot_capacity: Sequence[Any] = (),
) -> list[tuple[EligibleRelay, MachineCandidate]]:
    access = machine_access(
        conn,
        actor_id=actor_id,
        machine_ids=[relay.machine_id for relay in relays],
    )
    headroom = surface_headroom(conn, project_id=project_id, now=now)
    capacity = {entry.machine_id: entry for entry in snapshot_capacity}
    weighed: list[tuple[EligibleRelay, MachineCandidate]] = []
    for relay in relays:
        entry = access.get(relay.machine_id)
        reading = headroom.get((relay.machine_id, relay.surface))
        weighed.append(
            (
                relay,
                MachineCandidate(
                    machine_id=relay.machine_id,
                    hostname=relay.hostname,
                    surface=relay.surface,
                    headroom_percent=reading[0] if reading else None,
                    headroom_window=reading[1] if reading else None,
                    owned_by_requester=bool(entry and entry.owned_by_requester),
                    may_use=bool(entry and entry.may_use),
                    capacity_summary=(
                        capacity[relay.machine_id].summary()
                        if relay.machine_id in capacity
                        else None
                    ),
                    denial_reason=entry.denial_reason if entry else "machine unknown",
                ),
            )
        )
    return weighed


def _comparable_band(
    usable: list[tuple[EligibleRelay, MachineCandidate]],
) -> list[tuple[EligibleRelay, MachineCandidate]]:
    readable = [pair for pair in usable if pair[1].headroom_percent is not None]
    if not readable:
        return usable
    best = max(candidate.headroom_percent or 0.0 for _relay, candidate in readable)
    return [
        pair
        for pair in readable
        if (pair[1].headroom_percent or 0.0) >= best - COMPARABLE_HEADROOM_POINTS
    ]


def _reason(
    chosen: MachineCandidate,
    band: list[MachineCandidate],
    others: list[MachineCandidate],
) -> str:
    surface = chosen.surface
    if not others:
        return f"only usable machine offering {surface}"
    readings = ", ".join(
        f"{candidate.machine_id} {_percent(candidate.headroom_percent)}"
        for candidate in sorted([chosen, *others], key=lambda item: item.machine_id)
    )
    if chosen.headroom_percent is None:
        owned = (
            " and is the requester's own machine" if chosen.owned_by_requester else ""
        )
        return (
            f"no machine publishes a readable {surface} meter ({readings}); "
            f"chose {chosen.machine_id}{owned}"
        )
    if len(band) > 1:
        window = chosen.headroom_window or "plan limits"
        owned = (
            "it is the requester's own machine"
            if chosen.owned_by_requester
            else "no candidate is the requester's own machine, so machine id decided"
        )
        return (
            f"comparable {surface} headroom within "
            f"{int(COMPARABLE_HEADROOM_POINTS)} points ({readings}; {window}); "
            f"chose {chosen.machine_id} because {owned}"
        )
    window = chosen.headroom_window or "plan limits"
    return f"most {surface} headroom ({readings}; {window}); chose {chosen.machine_id}"


def place_launch(
    conn: Any,
    *,
    snapshot: EligibilitySnapshot,
    surface: str,
    machine_id: str | None,
    actor_id: int,
    project_id: int,
    now: str,
    fallback: bool = False,
) -> LaunchPreview:
    """Choose one eligible relay and say, in one sentence, why."""
    relays = tuple(snapshot.relays)
    if not relays:
        if "unsupported_surface" in snapshot.rejection_codes:
            outcome = "unsupported_surface"
        elif MACHINE_AT_CAPACITY in snapshot.rejection_codes:
            # Eligibility already dropped every machine whose lanes are full,
            # so this is a fleet with no room rather than one with no relay.
            outcome = MACHINE_AT_CAPACITY
        else:
            outcome = "no_eligible_relay"
        return LaunchPreview(
            outcome,
            surface,
            relays,
            considered_machine_ids=snapshot.considered_machine_ids,
            rejection_codes=snapshot.rejection_codes,
            machine_capacity=snapshot.machine_capacity,
        )
    weighed = _candidates(
        conn,
        relays=relays,
        actor_id=actor_id,
        project_id=project_id,
        now=now,
        snapshot_capacity=snapshot.machine_capacity,
    )
    usable = [pair for pair in weighed if pair[1].may_use]
    if not usable:
        denials = ", ".join(
            f"{candidate.machine_id}: {candidate.denial_reason or 'access denied'}"
            for _relay, candidate in weighed
        )
        return LaunchPreview(
            ACCESS_DENIED_OUTCOME,
            surface,
            relays,
            considered_machine_ids=snapshot.considered_machine_ids,
            rejection_codes=snapshot.rejection_codes,
            machine_capacity=snapshot.machine_capacity,
            placement_reason=(
                f"no eligible machine is usable by this actor ({denials})"
            ),
            machine_candidates=tuple(candidate for _relay, candidate in weighed),
        )
    if machine_id and len(usable) > 1:
        return LaunchPreview(
            "relay_ambiguous",
            surface,
            relays,
            considered_machine_ids=snapshot.considered_machine_ids,
            rejection_codes=snapshot.rejection_codes,
            machine_capacity=snapshot.machine_capacity,
            placement_reason=(
                f"machine {machine_id} answered with several relays; "
                "name one relay or retry"
            ),
            machine_candidates=tuple(candidate for _relay, candidate in weighed),
        )
    band = _comparable_band(usable)
    relay, chosen = min(
        band,
        key=lambda pair: (
            not pair[1].owned_by_requester,
            -(pair[1].headroom_percent or 0.0),
            pair[1].machine_id,
        ),
    )
    if machine_id:
        reason = f"machine {machine_id} pinned by the request"
    else:
        reason = _reason(
            chosen,
            [candidate for _relay, candidate in band],
            [
                candidate
                for _relay, candidate in weighed
                if candidate.machine_id != chosen.machine_id
            ],
        )
    candidates = tuple(
        MachineCandidate(**{**candidate.__dict__, "selected": True})
        if candidate.machine_id == chosen.machine_id
        else candidate
        for _relay, candidate in weighed
    )
    return LaunchPreview(
        "assigned_fallback" if fallback else "assigned",
        surface,
        relays,
        relay,
        snapshot.considered_machine_ids,
        snapshot.rejection_codes,
        snapshot.machine_capacity,
        placement_reason=reason,
        machine_candidates=candidates,
    )


__all__ = [
    "ACCESS_DENIED_OUTCOME",
    "COMPARABLE_HEADROOM_POINTS",
    "place_launch",
    "surface_headroom",
]
