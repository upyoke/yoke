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

from typing import Any, Dict, Iterable, List, Mapping, Optional, Set

from yoke_core.domain import db_backend
from yoke_core.domain.dependency_planning import BlockerDetail, evaluate_batch_gates
from yoke_core.domain.dependency_workflow_context import workflow_from_joined_values
from yoke_core.domain.frontier_edge_environments import edge_environments
from yoke_core.domain.item_ref_resolution import internal_ids_for_refs
from yoke_core.domain.item_terminal_resources import terminal_stage_ids
from yoke_core.domain.workflow_runtime import ENGINE_TERMINAL_STAGE_IDS

#: The gate points whose unsatisfied edges hold an item back, in gate order.
BLOCKING_GATE_POINTS = ("activation", "integration", "closure")

#: Edge-row keys, in presentation order.
FRONTIER_EDGE_FIELDS = (
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

# Blocker details for an edge whose blocker no longer resolves to an item.
_UNRESOLVED_BLOCKER = {
    "status": None,
    "terminal": False,
    "abandoned": False,
    "title": None,
    "project_id": None,
    "project_sequence": None,
}


def _item_facts(conn: Any, item_ids: Set[int]) -> Dict[int, Dict[str, Any]]:
    """Stage, title, project placement, terminal-ness and abandonment, by id."""
    ids = sorted(item_ids)
    if not ids:
        return {}
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    rows = conn.execute(
        "SELECT i.id, i.project_id, i.project_sequence, i.status, i.title, "
        "i.workflow_id, i.workflow_version_id, wv.version, wv.definition_json, "
        "wv.definition_digest FROM items i "
        "LEFT JOIN workflow_versions wv ON wv.id = i.workflow_version_id "
        f"WHERE i.id IN ({', '.join(marker for _ in ids)})",
        tuple(ids),
    ).fetchall()
    facts: Dict[int, Dict[str, Any]] = {}
    for raw in rows:
        row = dict(raw)
        status = str(row["status"] or "")
        runtime = workflow_from_joined_values(
            row["workflow_id"],
            row["workflow_version_id"],
            row["version"],
            row["definition_json"],
            row["definition_digest"],
        )
        facts[int(row["id"])] = {
            "project_id": int(row["project_id"]),
            "project_sequence": int(row["project_sequence"]),
            "status": status,
            "title": str(row["title"] or ""),
            "terminal": runtime is not None and status in terminal_stage_ids(runtime),
            "abandoned": status in ENGINE_TERMINAL_STAGE_IDS,
        }
    return facts


def frontier_dependency_edges(
    conn: Any,
    project_ids: Optional[Iterable[int]] = None,
    *,
    gate_blocks: Optional[Mapping[str, Mapping[str, List[BlockerDetail]]]] = None,
) -> List[Dict[str, Any]]:
    """Every unsatisfied blocking edge with a live dependent.

    ``project_ids`` keeps edges with either end in those projects, because a
    chain that crosses projects is one chain to the reader; ``None`` keeps all.
    ``gate_blocks`` maps each gate point to an evaluation the caller already
    holds, so a read evaluates each gate once; a missing gate is evaluated here.
    """
    pending: List[tuple[str, BlockerDetail]] = []
    for gate_point in BLOCKING_GATE_POINTS:
        blocks = (gate_blocks or {}).get(gate_point)
        if blocks is None:
            blocks = evaluate_batch_gates(
                conn, gate_point=gate_point, emit_events=False
            )
        for dependent_ref in sorted(blocks):
            pending.extend((dependent_ref, detail) for detail in blocks[dependent_ref])
    refs = {ref for ref, _ in pending} | {d.blocking_item for _, d in pending}
    ids = internal_ids_for_refs(conn, refs)
    facts = _item_facts(conn, set(ids.values()))
    scope = None if project_ids is None else {int(value) for value in project_ids}
    kept: List[tuple[str, BlockerDetail, Dict[str, Any], Optional[int]]] = []
    for dependent_ref, detail in pending:
        dependent = facts.get(ids.get(dependent_ref, -1))
        if dependent is None or dependent["terminal"]:
            continue
        blocker_id = ids.get(detail.blocking_item)
        blocker = facts.get(blocker_id if blocker_id is not None else -1)
        if scope is not None and not (
            dependent["project_id"] in scope
            or (blocker is not None and blocker["project_id"] in scope)
        ):
            continue
        kept.append((dependent_ref, detail, dependent, blocker_id if blocker else None))
    environments = edge_environments(
        conn,
        (
            (blocker_id, detail.satisfaction)
            for _, detail, _, blocker_id in kept
            if blocker_id
        ),
        {
            blocker_id: facts[blocker_id]["project_id"]
            for *_, blocker_id in kept
            if blocker_id
        },
    )
    edges: List[Dict[str, Any]] = []
    for dependent_ref, detail, dependent, blocker_id in kept:
        blocker = facts[blocker_id] if blocker_id is not None else _UNRESOLVED_BLOCKER
        edges.append(
            {
                "blocking_item": detail.blocking_item,
                "dependent_item": dependent_ref,
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
                "environment": environments.get((blocker_id, detail.satisfaction))
                if blocker_id is not None
                else None,
            }
        )
    return edges


__all__ = [
    "BLOCKING_GATE_POINTS",
    "FRONTIER_EDGE_FIELDS",
    "frontier_dependency_edges",
]
