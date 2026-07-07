"""Result dataclasses for the shared dependency-planning kernel.

These types are pure data shapes returned by ``dependency_planning``:

- ``BlockerDetail`` — one unsatisfied blocker, with enough rationale for
  operators and agents to understand why an edge exists.
- ``ItemGateEvaluation`` — gate evaluation result for a single item.
- ``CandidateItem`` — a candidate set entry with its blocker list.
- ``PlanResult`` — aggregate planning outcome for a candidate set.

The module has no DB or telemetry coupling; it only depends on
``dataclasses`` and ``typing``. Consumers should continue importing these
names from ``yoke_core.domain.dependency_planning`` (which re-exports
them) for stability.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class BlockerDetail:
    """Structured detail about a single unsatisfied blocker.

    Rich enough for operators and agents to understand why an edge
    exists and what must change.
    """

    blocking_item: str
    blocking_status: Optional[str]
    gate_point: str
    satisfaction: str
    rationale: str
    reason: str  # Human-readable evaluation reason from GateResult

    def to_dict(self) -> dict:
        return {
            "blocking_item": self.blocking_item,
            "blocking_status": self.blocking_status,
            "gate_point": self.gate_point,
            "satisfaction": self.satisfaction,
            "rationale": self.rationale,
            "reason": self.reason,
        }


@dataclass
class ItemGateEvaluation:
    """Result of evaluating all dependencies for one item at one gate point."""

    item_id: str
    gate_point: str
    is_blocked: bool
    unsatisfied_blockers: List[BlockerDetail] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "item_id": self.item_id,
            "gate_point": self.gate_point,
            "is_blocked": self.is_blocked,
            "unsatisfied_blockers": [b.to_dict() for b in self.unsatisfied_blockers],
        }


@dataclass
class CandidateItem:
    """An item in a candidate set with its gate evaluation."""

    item_id: str
    is_eligible: bool
    blockers: List[BlockerDetail] = field(default_factory=list)


@dataclass
class PlanResult:
    """Result of ordered planning for a candidate set at a gate point.

    Attributes:
        gate_point: The gate evaluated.
        eligible: Items that are currently clear at this gate, in
            topological order (dependencies first).
        blocked: Items with unsatisfied blockers, with detail.
        has_cycle: True if a cycle was detected among eligible items.
        cycle_items: Items involved in the cycle (if any).
    """

    gate_point: str
    eligible: List[str] = field(default_factory=list)
    blocked: List[CandidateItem] = field(default_factory=list)
    has_cycle: bool = False
    cycle_items: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "gate_point": self.gate_point,
            "eligible": self.eligible,
            "blocked": [
                {
                    "item_id": c.item_id,
                    "blockers": [b.to_dict() for b in c.blockers],
                }
                for c in self.blocked
            ],
            "has_cycle": self.has_cycle,
            "cycle_items": self.cycle_items,
        }
