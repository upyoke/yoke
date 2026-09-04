"""Machine access applied where launch capacity is actually consumed.

Launch preview and launch create both resolve their relays through one
eligibility snapshot, so filtering that snapshot is the single point at which
a machine the calling actor may not use stops being launchable — and the
rejection code carries the setting that decided it into the refusal message.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.machine_access_authority import actor_may_use_machine
from yoke_core.domain.session_launch_types import EligibilitySnapshot


ACCESS_DENIED_REJECTION = "machine_access_denied"


def filter_by_machine_access(
    conn: Any,
    snapshot: EligibilitySnapshot,
    *,
    actor_id: int,
    project_id: int,
    is_admin: bool = False,
) -> tuple[EligibilitySnapshot, dict[str, str]]:
    """Drop relays on machines this actor may not use.

    Returns the narrowed snapshot plus the per-machine reason for each drop,
    so the caller can name the setting rather than reporting a bare code.
    """
    kept = []
    reasons: dict[str, str] = {}
    for relay in snapshot.relays:
        decision = actor_may_use_machine(
            conn,
            machine_id=relay.machine_id,
            actor_id=int(actor_id),
            project_id=int(project_id),
            is_admin=bool(is_admin),
        )
        if decision.allowed:
            kept.append(relay)
            continue
        reasons[relay.machine_id] = f"{decision.setting}: {decision.reason}"
    if not reasons:
        return snapshot, {}
    codes = tuple(sorted(set(snapshot.rejection_codes) | {ACCESS_DENIED_REJECTION}))
    details = tuple(sorted(set(snapshot.rejection_details) | set(reasons.values())))
    return (
        EligibilitySnapshot(
            relays=tuple(kept),
            considered_machine_ids=snapshot.considered_machine_ids,
            rejection_codes=codes,
            machine_capacity=snapshot.machine_capacity,
            rejection_details=details,
        ),
        reasons,
    )


__all__ = ["ACCESS_DENIED_REJECTION", "filter_by_machine_access"]
