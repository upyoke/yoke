"""Every unsatisfied dependency edge the Frontier draws as its Waiting graph.

The Frontier shows what waits on what as a graph, so it needs the edges
themselves — every blocker of an item, the gate each one holds (start, merge
or close), the condition that clears it, and the rationale its author gave —
rather than one reason sentence per waiting item. Satisfaction is decided by
the shared dependency kernel (:func:`evaluate_batch_gates`); this module only
adds what a reader needs to place and explain each edge:

* the blocker's stage, title, whether it is terminal, and whether it was
  abandoned — ended by the engine (cancelled, stopped) rather than completed —
  so a blocker the page does not otherwise show still draws as a tile, and
  only an abandoned one reads as an edge that will never clear;
* for ``fact:deployed:<env>``, where the blocker's delivery stands in that
  environment and whether any delivery flow can take it there at all
  (:mod:`frontier_edge_environments`).

``coordination_only`` edges never block, so they are never returned. An edge
whose dependent is terminal has nothing left to gate and is dropped. An edge
whose blocker no longer resolves to an item is still returned, with empty
blocker details, so the dependent is drawn waiting on it rather than vanishing
from the graph. Cycles, self-edges included, are returned as they are: the
kernel evaluates edges, not orders, and the Frontier names a deadlock rather
than hiding one.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from yoke_core.domain.dependency_cycles_read import (
    GateBlocks,
    cycles_in,
    live_blocking_edges,
)
from yoke_core.domain.frontier_edge_environments import edge_environments

#: Edge-row keys, in presentation order.
FRONTIER_EDGE_FIELDS = (
    "dependency_id",
    "blocking_item",
    "dependent_item",
    "gate_point",
    "satisfaction",
    "rationale",
    "blocking_stage",
    "blocking_terminal",
    "blocking_abandoned",
    "blocking_title",
    "blocking_project_id",
    "blocking_project_sequence",
    "dependent_project_id",
    "dependent_project_sequence",
    "environment",
)

#: Deadlock-row keys: the loop's items, the edges closing it, who it strands.
FRONTIER_CYCLE_FIELDS = ("items", "edges", "stranded")

# Blocker details for an edge whose blocker no longer resolves to an item.
_UNRESOLVED_BLOCKER = {
    "status": None,
    "terminal": False,
    "abandoned": False,
    "title": None,
    "project_id": None,
    "project_sequence": None,
}


def frontier_dependency_graph(
    conn: Any,
    project_ids: Optional[Iterable[int]] = None,
    *,
    gate_blocks: Optional[GateBlocks] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """The Waiting graph: every live blocking edge, and every deadlock.

    ``project_ids`` keeps edges with either end in those projects, and loops
    with any member in them, because a chain that crosses projects is one
    chain to the reader; ``None`` keeps all. ``gate_blocks`` maps each gate
    point to an evaluation the caller already holds, so a read evaluates each
    gate once; a missing gate is evaluated here.
    """
    live = live_blocking_edges(conn, gate_blocks=gate_blocks)
    scope = None if project_ids is None else {int(value) for value in project_ids}
    cycles = cycles_in(live, scope)
    # A kept loop draws whole, even through items outside the scope.
    looped = {e.dependency_id for cycle in cycles for e in cycle.edges}
    kept = [
        edge
        for edge in live
        if scope is None
        or edge.dependent["project_id"] in scope
        or (edge.blocker is not None and edge.blocker["project_id"] in scope)
        or edge.detail.dependency_id in looped
    ]
    environments = edge_environments(
        conn,
        (
            (edge.blocker_id, edge.detail.satisfaction)
            for edge in kept
            if edge.blocker_id
        ),
        {
            edge.blocker_id: edge.blocker["project_id"]
            for edge in kept
            if edge.blocker_id and edge.blocker
        },
    )
    rows: List[Dict[str, Any]] = []
    for edge in kept:
        detail, dependent = edge.detail, edge.dependent
        blocker = edge.blocker or _UNRESOLVED_BLOCKER
        rows.append(
            {
                "dependency_id": detail.dependency_id,
                "blocking_item": detail.blocking_item,
                "dependent_item": edge.dependent_ref,
                "gate_point": detail.gate_point,
                "satisfaction": detail.satisfaction,
                "rationale": detail.rationale,
                "blocking_stage": blocker["status"],
                "blocking_terminal": blocker["terminal"],
                "blocking_abandoned": blocker["abandoned"],
                "blocking_title": blocker["title"],
                "blocking_project_id": blocker["project_id"],
                "blocking_project_sequence": blocker["project_sequence"],
                "dependent_project_id": dependent["project_id"],
                "dependent_project_sequence": dependent["project_sequence"],
                "environment": environments.get(
                    (edge.blocker_id, detail.satisfaction)
                )
                if edge.blocker_id is not None
                else None,
            }
        )
    return {
        "dependency_edges": rows,
        "dependency_cycles": [cycle.to_dict() for cycle in cycles],
    }


__all__ = [
    "FRONTIER_CYCLE_FIELDS",
    "FRONTIER_EDGE_FIELDS",
    "frontier_dependency_graph",
]
