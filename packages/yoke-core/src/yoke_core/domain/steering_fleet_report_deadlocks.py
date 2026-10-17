"""The steering report's dependency-deadlock section.

A loop of blocking dependency edges among live items never resolves on its
own: no item in it can move first, and every item waiting on it is stranded
too. Each loop the backend detector finds
(:mod:`yoke_core.domain.dependency_cycles`) prints once, naming its items,
every edge with its id, the stranded work, and the recovery.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.dependency_cycles import RECOVERY, DependencyCycle
from yoke_core.domain.steering_fleet_report_render_text import SECTION_LIMIT, capped

HEADING = (
    "dependency deadlocks — live items waiting on each other; no item in a "
    "loop can move first"
)


def deadlock_section(report: Any) -> list[str]:
    """The section, heading and recovery included; empty when there are none."""
    cycles: tuple[DependencyCycle, ...] = getattr(report, "deadlocks", ())
    if not cycles:
        return []
    lines = [f"  {cycle.describe()}" for cycle in cycles[:SECTION_LIMIT]]
    return [
        f"{HEADING}:",
        *capped(lines, len(cycles)),
        f"  recovery: {RECOVERY}",
    ]


def deadlock_fingerprint(report: Any) -> list[Any]:
    """Age-blind identity: which loops exist, through which edges."""
    return sorted(
        (cycle.key, tuple(sorted(str(edge.dependency_id) for edge in cycle.edges)))
        for cycle in getattr(report, "deadlocks", ())
    )


__all__ = ["HEADING", "deadlock_fingerprint", "deadlock_section"]
