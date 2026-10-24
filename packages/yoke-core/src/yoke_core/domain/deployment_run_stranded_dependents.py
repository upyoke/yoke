"""Refuse a new release that would strand dependents of a not-yet-released item.

A carried item merged into the candidate but not yet at its workflow's release
stage is skipped, and a carried dependent whose blocker does not ship in the
same run is skipped too -- transitively, because a skipped dependent strands
its own dependents. Creating that run leaves the whole chain for a later
release and an operator to repair it item by item, so creation refuses
instead and names the wait. When nothing carried depends on such an item the
run is created and the skipped-candidate notice warns about it as before.

Only creation refuses: validating a run that already exists reports the
notice, so an existing run is never newly blocked.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from typing import Any

from yoke_core.domain.deployment_run_skipped_candidates import (
    SkippedCandidates,
    describe_skipped,
    skipped_candidates,
)
from yoke_core.domain.deployment_run_unheld_candidates import CustodyResolution
from yoke_core.domain.item_ref_render import render_item_ref_lookup

#: Stable reason code the create refusal leads with.
STRANDING_REASON = "release_stranding_unreleased_blocker"


def stranded_dependents(skipped: SkippedCandidates) -> dict[int, tuple[int, ...]]:
    """Each not-yet-released carried item and the skipped dependents it strands.

    A dependent counts when its chain of blocked edges leads back to that
    item through other skipped carried dependents.
    """
    roots = {item_id for item_id, _ in skipped.rework}
    dependents_of: dict[int, set[int]] = defaultdict(set)
    for dependent, blocker, _ in skipped.blocked:
        dependents_of[blocker].add(dependent)
    stranded: dict[int, tuple[int, ...]] = {}
    for root in sorted(roots):
        reached: set[int] = set()
        frontier = [root]
        while frontier:
            for dependent in dependents_of.get(frontier.pop(), ()):
                if dependent not in reached and dependent not in roots:
                    reached.add(dependent)
                    frontier.append(dependent)
        if reached:
            stranded[root] = tuple(sorted(reached))
    return stranded


def stranding_refusal(conn: Any, skipped: SkippedCandidates | None) -> str:
    """The create refusal for *skipped*, or ``""`` when nothing is stranded."""
    if skipped is None:
        return ""
    stranded = stranded_dependents(skipped)
    if not stranded:
        return ""
    status = dict(skipped.rework)
    ref = render_item_ref_lookup(
        conn, [i for root, deps in stranded.items() for i in (root, *deps)]
    )
    named = "; ".join(
        f"{ref(root)} (status={status[root]}) strands "
        + ", ".join(ref(dependent) for dependent in dependents)
        for root, dependents in stranded.items()
    )
    return (
        f"{STRANDING_REASON}: this candidate carries merged items not yet at "
        "their release stage, and carried dependents need them, so this run "
        f"would skip those dependents: {named}. Recovery: wait until each "
        "named item reaches its release stage, then retry "
        "`yoke deployment-runs create`."
    )


def skipped_candidate_verdict(
    conn: Any,
    run_id: str,
    *,
    custody: CustodyResolution | None,
    carried_work: Mapping[str, Any] | None,
    refuse: bool,
) -> tuple[str, str]:
    """``(refusal, notice)`` from one skipped-candidate resolution.

    The refusal is ``""`` unless *refuse* is set and a
    not-yet-released carried item strands a carried dependent.
    """
    skipped = skipped_candidates(
        conn, run_id, custody=custody, carried_work=carried_work
    )
    refusal = stranding_refusal(conn, skipped) if refuse else ""
    return refusal, describe_skipped(conn, run_id, skipped)


__all__ = [
    "STRANDING_REASON",
    "skipped_candidate_verdict",
    "stranded_dependents",
    "stranding_refusal",
]
