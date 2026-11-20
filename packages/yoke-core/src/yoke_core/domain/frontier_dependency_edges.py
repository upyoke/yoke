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

from typing import AbstractSet, Any, Dict, Iterable, List, Optional

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
    "blocking_hidden",
)

#: How a served edge names a blocker in a project the reader cannot see.
HIDDEN_BLOCKER_LABEL = "Hidden work"
HIDDEN_BLOCKER_TITLE = "Waiting on work in a project you cannot see"

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
    visible_project_ids: Optional[AbstractSet[int]] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """The Waiting graph: every live blocking edge, and every deadlock.

    ``project_ids`` keeps edges with either end in those projects, and loops
    with any member in them, because a chain that crosses projects is one
    chain to the reader; ``None`` keeps all. ``gate_blocks`` maps each gate
    point to an evaluation the caller already holds, so a read evaluates each
    gate once; a missing gate is evaluated here.

    ``visible_project_ids`` is the reader's readable set (``None`` for local
    and unscoped reads). Edges with a hidden end are left out before loops
    are found, so every loop member and stranded item is visible. A visible
    item waiting on hidden work still draws waiting: its edge is served with
    the blocker named only as numbered hidden work (:func:`_hidden_rows`).
    """
    live = live_blocking_edges(conn, gate_blocks=gate_blocks)
    scope = None if project_ids is None else {int(value) for value in project_ids}
    hidden: List[Any] = []
    if visible_project_ids is not None:
        visible = visible_project_ids
        shown = [e for e in live if e.dependent["project_id"] in visible]
        live = [e for e in shown if e.blocker is None or e.blocker["project_id"] in visible]
        hidden = [
            e
            for e in shown
            if e.blocker is not None
            and e.blocker["project_id"] not in visible
            and (scope is None or e.dependent["project_id"] in scope)
        ]
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
                "environment": environments.get((edge.blocker_id, detail.satisfaction))
                if edge.blocker_id is not None
                else None,
                "blocking_hidden": False,
            }
        )
    return {
        "dependency_edges": rows + _hidden_rows(hidden),
        "dependency_cycles": [cycle.to_dict() for cycle in cycles],
    }


def _hidden_rows(edges: List[Any]) -> List[Dict[str, Any]]:
    """Edges onto hidden work, naming nothing of the blocker.

    Each edge gets its own label, so two items waiting on the same hidden
    item do not reveal that they share it. The rationale is withheld because
    it can describe the hidden work.
    """
    rows: List[Dict[str, Any]] = []
    ordered = sorted(edges, key=lambda e: e.detail.dependency_id)
    for number, edge in enumerate(ordered, start=1):
        rows.append(
            {
                "dependency_id": edge.detail.dependency_id,
                "blocking_item": f"{HIDDEN_BLOCKER_LABEL} {number}",
                "dependent_item": edge.dependent_ref,
                "gate_point": edge.detail.gate_point,
                "satisfaction": edge.detail.satisfaction,
                "rationale": "",
                "blocking_stage": None,
                "blocking_terminal": False,
                "blocking_abandoned": False,
                "blocking_title": HIDDEN_BLOCKER_TITLE,
                "blocking_project_id": None,
                "blocking_project_sequence": None,
                "dependent_project_id": edge.dependent["project_id"],
                "dependent_project_sequence": edge.dependent["project_sequence"],
                "environment": None,
                "blocking_hidden": True,
            }
        )
    return rows


__all__ = [
    "HIDDEN_BLOCKER_LABEL",
    "HIDDEN_BLOCKER_TITLE",
    "FRONTIER_CYCLE_FIELDS",
    "FRONTIER_EDGE_FIELDS",
    "frontier_dependency_graph",
]
