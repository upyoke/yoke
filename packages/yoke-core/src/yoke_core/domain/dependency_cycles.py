"""Dependency deadlocks: live items that each wait on another in a loop.

An unsatisfied blocking edge (``activation``, ``integration`` or ``closure``)
holds its dependent until the blocker moves. When those edges close a loop,
no item in it can move first, and everything waiting on the loop is stranded
with it. ``coordination_only`` edges never hold anything, so they never take
part. This module is the one place that finds such loops: the dependency
writes refuse to close one, and the Frontier, the fleet watch and the steering
report name the ones that exist. It reads no database; the edges come from
:mod:`yoke_core.domain.dependency_cycles_read`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set

from yoke_contracts.refusal_recovery import compose_refusal

#: What a reader runs to break a loop: one edge becomes ordering advice.
RECOVERY = (
    "make one edge in the loop coordination_only with `yoke items dependency "
    "update DEPENDENT BLOCKING --match-gate-point GATE --gate-point "
    "coordination_only --rationale TEXT`, or route the ordering decision to "
    "steering with `yoke say --steering --stdin`"
)


@dataclass(frozen=True)
class WaitEdge:
    """One unsatisfied blocking edge: ``dependent_item`` waits on ``blocking_item``."""

    dependency_id: Optional[int]
    dependent_item: str
    blocking_item: str
    gate_point: str
    satisfaction: str

    def describe(self, proposed: bool = False) -> str:
        """``proposed`` marks the refused write, whose id was rolled back."""
        number = (
            "proposed "
            if proposed
            else f"#{self.dependency_id} "
            if self.dependency_id is not None
            else ""
        )
        return (
            f"{number}{self.dependent_item} waits on {self.blocking_item} "
            f"({self.gate_point}, {self.satisfaction})"
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dependency_id": self.dependency_id,
            "dependent_item": self.dependent_item,
            "blocking_item": self.blocking_item,
            "gate_point": self.gate_point,
            "satisfaction": self.satisfaction,
        }


@dataclass(frozen=True)
class DependencyCycle:
    """A loop of waiting items, the edges that close it, and who it strands.

    ``items`` and ``edges`` follow the loop when it is a single ring;
    ``stranded`` is every item outside the loop that waits on it, directly or
    through other waiting items.
    """

    items: tuple[str, ...]
    edges: tuple[WaitEdge, ...]
    stranded: tuple[str, ...] = ()

    @property
    def key(self) -> str:
        return ",".join(sorted(self.items))

    def loop_text(self) -> str:
        if len(self.items) == 1:
            return f"{self.items[0]} waits on itself"
        return " → ".join((*self.items, self.items[0]))

    def describe(self, proposed: frozenset[int] = frozenset()) -> str:
        """The loop, each edge with its id, and the work it strands."""
        text = f"{self.loop_text()}: " + "; ".join(
            edge.describe(edge.dependency_id in proposed) for edge in self.edges
        )
        if self.stranded:
            text += f"; strands {', '.join(self.stranded)}"
        return text

    @classmethod
    def from_dict(cls, row: Mapping[str, Any]) -> "DependencyCycle":
        """Rebuild a served row, e.g. one ``charge.schedule`` returned."""
        return cls(
            items=tuple(str(ref) for ref in row.get("items") or ()),
            edges=tuple(
                WaitEdge(
                    dependency_id=edge.get("dependency_id"),
                    dependent_item=str(edge.get("dependent_item") or ""),
                    blocking_item=str(edge.get("blocking_item") or ""),
                    gate_point=str(edge.get("gate_point") or ""),
                    satisfaction=str(edge.get("satisfaction") or ""),
                )
                for edge in row.get("edges") or ()
            ),
            stranded=tuple(str(ref) for ref in row.get("stranded") or ()),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "items": list(self.items),
            "edges": [edge.to_dict() for edge in self.edges],
            "stranded": list(self.stranded),
        }


class DependencyCycleError(ValueError):
    """A dependency write that would close a deadlock, refused before commit."""

    code = "dependency_cycle"

    def __init__(
        self,
        change: str,
        cycles: Sequence[DependencyCycle],
        proposed: frozenset[int] = frozenset(),
    ) -> None:
        self.cycles = tuple(cycles)
        loops = " | ".join(cycle.describe(proposed) for cycle in self.cycles)
        super().__init__(
            compose_refusal(
                f"dependency_cycle: {change} would deadlock live work, because no item in the loop can move first — {loops}. Nothing was written.",
                recovery=f"{RECOVERY}.",
            )
        )


def _components(graph: Dict[str, List[str]]) -> List[List[str]]:
    """Strongly connected groups, by Tarjan's algorithm without recursion."""
    index: Dict[str, int] = {}
    low: Dict[str, int] = {}
    stack: List[str] = []
    on_stack: Set[str] = set()
    groups: List[List[str]] = []
    for root in sorted(graph):
        if root in index:
            continue
        work = [(root, iter(graph[root]))]
        index[root] = low[root] = len(index)
        stack.append(root)
        on_stack.add(root)
        while work:
            node, successors = work[-1]
            advanced = False
            for nxt in successors:
                if nxt not in index:
                    index[nxt] = low[nxt] = len(index)
                    stack.append(nxt)
                    on_stack.add(nxt)
                    work.append((nxt, iter(graph[nxt])))
                    advanced = True
                    break
                if nxt in on_stack:
                    low[node] = min(low[node], index[nxt])
            if advanced:
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
            if low[node] == index[node]:
                group: List[str] = []
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    group.append(member)
                    if member == node:
                        break
                groups.append(group)
    return groups


def _ring_order(
    members: Set[str], inside: List[WaitEdge]
) -> tuple[tuple[str, ...], tuple[WaitEdge, ...]]:
    """Follow a single ring from its first item; any other shape sorts."""
    outgoing: Dict[str, List[WaitEdge]] = {}
    for edge in inside:
        outgoing.setdefault(edge.dependent_item, []).append(edge)
    if len(inside) == len(members) and all(
        len(outgoing.get(m, ())) == 1 for m in members
    ):
        items: List[str] = []
        edges: List[WaitEdge] = []
        node = min(members)
        while node not in items:
            items.append(node)
            edge = outgoing[node][0]
            edges.append(edge)
            node = edge.blocking_item
        return tuple(items), tuple(edges)
    ordered = sorted(
        inside, key=lambda e: (e.dependent_item, e.blocking_item, e.gate_point)
    )
    return tuple(sorted(members)), tuple(ordered)


def find_cycles(edges: Iterable[WaitEdge]) -> List[DependencyCycle]:
    """Every deadlock among ``edges``, with the items each one strands."""
    edges = list(edges)
    waits_on: Dict[str, List[str]] = {}
    waited_by: Dict[str, List[str]] = {}
    for edge in edges:
        waits_on.setdefault(edge.dependent_item, []).append(edge.blocking_item)
        waits_on.setdefault(edge.blocking_item, [])
        waited_by.setdefault(edge.blocking_item, []).append(edge.dependent_item)
    for successors in waits_on.values():
        successors.sort()
    cycles: List[DependencyCycle] = []
    for group in _components(waits_on):
        members = set(group)
        inside = [
            e
            for e in edges
            if e.dependent_item in members and e.blocking_item in members
        ]
        if len(members) == 1 and not inside:
            continue
        items, ordered = _ring_order(members, inside)
        cycles.append(DependencyCycle(items, ordered, _downstream(members, waited_by)))
    return sorted(cycles, key=lambda cycle: cycle.key)


def _downstream(members: Set[str], waited_by: Dict[str, List[str]]) -> tuple[str, ...]:
    seen: Set[str] = set()
    frontier = list(members)
    while frontier:
        for waiter in waited_by.get(frontier.pop(), ()):
            if waiter not in seen and waiter not in members:
                seen.add(waiter)
                frontier.append(waiter)
    return tuple(sorted(seen))


__all__ = [
    "DependencyCycle",
    "DependencyCycleError",
    "RECOVERY",
    "WaitEdge",
    "find_cycles",
]
