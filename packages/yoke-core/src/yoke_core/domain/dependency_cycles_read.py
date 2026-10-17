"""The live waiting graph, read from the control plane, and its deadlocks.

Satisfaction is decided by the shared dependency kernel
(:func:`evaluate_batch_gates`). An edge counts while it is unsatisfied and
its dependent is not terminal: a finished or abandoned item has nothing left
to hold back, and a loop through one is a blocker that will never clear, not
a deadlock. Each read evaluates every gate once and can hand the caller the
evaluation it already holds.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set

from yoke_core.domain import db_backend
from yoke_core.domain.dependency_cycles import (
    DependencyCycle,
    DependencyCycleError,
    WaitEdge,
    find_cycles,
)
from yoke_core.domain.dependency_planning import BlockerDetail, evaluate_batch_gates
from yoke_core.domain.dependency_workflow_context import workflow_from_joined_values
from yoke_core.domain.item_ref_resolution import internal_ids_for_refs
from yoke_core.domain.item_terminal_resources import terminal_stage_ids
from yoke_core.domain.workflow_runtime import ENGINE_TERMINAL_STAGE_IDS

#: The gate points whose unsatisfied edges hold an item back, in gate order.
BLOCKING_GATE_POINTS = ("activation", "integration", "closure")

GateBlocks = Mapping[str, Mapping[str, List[BlockerDetail]]]


@dataclass(frozen=True)
class LiveEdge:
    """One unsatisfied blocking edge whose dependent is still live."""

    dependent_ref: str
    detail: BlockerDetail
    dependent: Dict[str, Any]
    blocker_id: Optional[int]
    blocker: Optional[Dict[str, Any]]

    def wait_edge(self) -> WaitEdge:
        return WaitEdge(
            dependency_id=self.detail.dependency_id,
            dependent_item=self.dependent_ref,
            blocking_item=self.detail.blocking_item,
            gate_point=self.detail.gate_point,
            satisfaction=self.detail.satisfaction,
        )


def item_facts(conn: Any, item_ids: Set[int]) -> Dict[int, Dict[str, Any]]:
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


def live_blocking_edges(
    conn: Any, *, gate_blocks: Optional[GateBlocks] = None
) -> List[LiveEdge]:
    """Every unsatisfied blocking edge whose dependent is not terminal.

    ``gate_blocks`` maps each gate point to an evaluation the caller already
    holds; a missing gate is evaluated here. An edge whose blocker no longer
    resolves to an item is kept with ``blocker`` unset.
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
    facts = item_facts(conn, set(ids.values()))
    live: List[LiveEdge] = []
    for dependent_ref, detail in pending:
        dependent = facts.get(ids.get(dependent_ref, -1))
        if dependent is None or dependent["terminal"]:
            continue
        blocker_id = ids.get(detail.blocking_item)
        blocker = facts.get(blocker_id if blocker_id is not None else -1)
        live.append(
            LiveEdge(
                dependent_ref,
                detail,
                dependent,
                blocker_id if blocker else None,
                blocker,
            )
        )
    return live


def cycles_in(
    live: Iterable[LiveEdge], project_ids: Optional[Iterable[int]] = None
) -> List[DependencyCycle]:
    """Deadlocks among ``live``; ``project_ids`` keeps loops touching them.

    A loop is found over every project's edges, because a loop that crosses
    projects is one loop, and then kept when any member or any item it
    strands is in scope: either way the scope has work that cannot move.
    """
    live = list(live)
    cycles = find_cycles(edge.wait_edge() for edge in live)
    if project_ids is None:
        return cycles
    scope = {int(value) for value in project_ids}
    projects = {edge.dependent_ref: edge.dependent["project_id"] for edge in live}
    return [
        cycle
        for cycle in cycles
        if any(projects.get(ref) in scope for ref in (*cycle.items, *cycle.stranded))
    ]


def dependency_cycles(
    conn: Any,
    project_ids: Optional[Iterable[int]] = None,
    *,
    gate_blocks: Optional[GateBlocks] = None,
) -> List[DependencyCycle]:
    """Every live deadlock, optionally only those touching ``project_ids``."""
    return cycles_in(live_blocking_edges(conn, gate_blocks=gate_blocks), project_ids)


def seat_cycles(
    conn: Any, cycles: Iterable[DependencyCycle], members: Optional[Set[int]]
) -> List[DependencyCycle]:
    """Loops holding or stranding a narrowed seat's items; all for a project seat."""
    cycles = list(cycles)
    if members is None:
        return cycles
    touched = {ref for c in cycles for ref in (*c.items, *c.stranded)}
    ids = internal_ids_for_refs(conn, touched)
    return [
        cycle
        for cycle in cycles
        if any(ids.get(ref) in members for ref in (*cycle.items, *cycle.stranded))
    ]


def refuse_cycles_through(
    conn: Any, dependency_ids: Iterable[int], change: str
) -> None:
    """Roll back and refuse when a just-written edge closes a deadlock.

    Called inside the write's own transaction, before commit, so the kernel
    judges the edge exactly as stored — including whether it is already
    satisfied — and a refusal leaves nothing behind.
    """
    written = frozenset(int(value) for value in dependency_ids)
    if not written:
        return
    closed = [
        cycle
        for cycle in dependency_cycles(conn)
        if any(edge.dependency_id in written for edge in cycle.edges)
    ]
    if closed:
        conn.rollback()
        raise DependencyCycleError(change, closed, written)


__all__ = [
    "BLOCKING_GATE_POINTS",
    "LiveEdge",
    "cycles_in",
    "dependency_cycles",
    "item_facts",
    "live_blocking_edges",
    "refuse_cycles_through",
    "seat_cycles",
]
