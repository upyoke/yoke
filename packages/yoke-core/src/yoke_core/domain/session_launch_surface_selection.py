"""Exact-first, explicitly gated surface selection for session launches."""

from __future__ import annotations

from typing import Any

from yoke_contracts.executor_labels import (
    KNOWN_SURFACE_LABELS,
    canonical_harness_id,
)
from yoke_contracts.session_control.capabilities import capability_for_surface
from yoke_core.domain.session_launch_eligibility import derive_launch_eligibility
from yoke_core.domain.session_launch_placement import place_launch
from yoke_core.domain.session_launch_store import utc_now
from yoke_core.domain.session_launch_types import (
    EligibilitySnapshot,
    EligibleRelay,
    LaunchAuthorization,
    LaunchEligibilityPort,
    LaunchPreview,
    ensure_operator,
)


def _fallback_surfaces(requested_surface: str) -> tuple[str, ...]:
    """Return stable same-family alternatives with a native create interface."""
    try:
        family = canonical_harness_id(requested_surface)
    except ValueError:
        return ()
    candidates = []
    for surface in KNOWN_SURFACE_LABELS:
        capability = capability_for_surface(surface)
        if (
            surface != requested_surface
            and canonical_harness_id(surface) == family
            and capability is not None
            and capability.create != "none"
        ):
            candidates.append(surface)
    return tuple(sorted(candidates))


def _fallback_snapshot(
    conn: Any,
    *,
    project_id: int,
    requested_surface: str,
    machine_id: str | None,
    now: str,
    eligibility: LaunchEligibilityPort,
) -> EligibilitySnapshot:
    selected_by_machine: dict[str, EligibleRelay] = {}
    considered: set[str] = set()
    rejected: set[str] = set()
    capacities: dict[str, Any] = {}
    for surface in _fallback_surfaces(requested_surface):
        snapshot = eligibility(
            conn,
            project_id=project_id,
            surface=surface,
            machine_id=machine_id,
            now=now,
        )
        considered.update(snapshot.considered_machine_ids)
        rejected.update(snapshot.rejection_codes)
        for entry in snapshot.machine_capacity:
            capacities.setdefault(entry.machine_id, entry)
        for relay in snapshot.relays:
            selected_by_machine.setdefault(relay.machine_id, relay)
    return EligibilitySnapshot(
        tuple(
            sorted(
                selected_by_machine.values(),
                key=lambda relay: (relay.machine_id, relay.relay_id),
            )
        ),
        tuple(sorted(considered)),
        tuple(sorted(rejected)),
        tuple(capacities[machine] for machine in sorted(capacities)),
    )


def preview_launch(
    conn: Any,
    *,
    auth: LaunchAuthorization,
    project_id: int,
    surface: str,
    machine_id: str | None = None,
    allow_surface_fallback: bool = False,
    surface_fallback_enabled: bool = False,
    now: str | None = None,
    eligibility: LaunchEligibilityPort = derive_launch_eligibility,
) -> LaunchPreview:
    """Prefer the requested surface and use fallback only through both gates."""
    ensure_operator(auth)
    current = now or utc_now()
    exact = eligibility(
        conn,
        project_id=project_id,
        surface=surface,
        machine_id=machine_id,
        now=current,
    )
    exact_preview = place_launch(
        conn,
        snapshot=exact,
        surface=surface,
        machine_id=machine_id,
        actor_id=auth.actor_id,
        project_id=project_id,
        now=current,
    )
    if exact.relays:
        return exact_preview
    if surface.endswith("-desktop") and exact_preview.outcome == "unsupported_surface":
        return exact_preview
    if not allow_surface_fallback:
        return exact_preview
    if not surface_fallback_enabled:
        return LaunchPreview(
            "surface_fallback_disabled",
            surface,
            exact_preview.eligible_relays,
        )
    fallback = _fallback_snapshot(
        conn,
        project_id=project_id,
        requested_surface=surface,
        machine_id=machine_id,
        now=current,
        eligibility=eligibility,
    )
    if not fallback.relays:
        return exact_preview
    return place_launch(
        conn,
        snapshot=fallback,
        surface=surface,
        machine_id=machine_id,
        actor_id=auth.actor_id,
        project_id=project_id,
        now=current,
        fallback=True,
    )


__all__ = ["preview_launch"]
