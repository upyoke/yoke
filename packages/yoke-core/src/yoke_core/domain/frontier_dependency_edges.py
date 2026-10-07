"""Every unsatisfied dependency edge the Frontier draws as its Waiting graph.

The Frontier shows what waits on what as a graph, so it needs the edges
themselves — every blocker of an item, the gate each one holds (start, merge
or close), the condition that clears it, and the rationale its author gave —
rather than one reason sentence per waiting item. Satisfaction is decided by
the shared dependency kernel (:func:`evaluate_batch_gates`); this module only
adds what a reader needs to place and explain each edge:

* the blocker's stage, title and terminal-ness, so a blocker the page does not
  otherwise show still draws as a tile, and a cancelled one reads as an edge
  that will never clear;
* for ``fact:deployed:<env>``, where the blocker's delivery stands in that
  environment and whether any delivery flow can take it there at all.

``coordination_only`` edges never block, so they are never returned. An edge
whose dependent is terminal has nothing left to gate and is dropped. Cycles
are returned as they are: the kernel evaluates edges, not orders, and the
Frontier names a deadlock rather than hiding one.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Set

from yoke_core.domain import db_backend
from yoke_core.domain.dependency_planning import BlockerDetail, evaluate_batch_gates
from yoke_core.domain.dependency_satisfaction import read_deployed_environment_fact
from yoke_core.domain.dependency_types import deployed_environment
from yoke_core.domain.dependency_workflow_context import workflow_from_joined_values
from yoke_core.domain.deployment_flow_state import FLOW_STATUS_ACTIVE
from yoke_core.domain.deployment_item_flow_resolution import item_completion_flows
from yoke_core.domain.item_ref_resolution import internal_ids_for_refs
from yoke_core.domain.item_terminal_resources import terminal_stage_ids
from yoke_core.domain.runs import TERMINAL_RUN_STATUSES

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
    "blocking_title",
    "blocking_project_id",
    "blocking_project_sequence",
    "dependent_project_id",
    "dependent_project_sequence",
    "environment",
)

#: Where a blocker's delivery stands in the environment an edge waits on.
DELIVERY_LIVE = "live"
DELIVERY_DEPLOYING = "deploying"
DELIVERY_NOT_DEPLOYED = "not deployed"
DELIVERY_UNREGISTERED = "unregistered"


def _marker(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _item_facts(conn: Any, item_ids: Set[int]) -> Dict[int, Dict[str, Any]]:
    """Stage, title, project placement and terminal-ness, keyed by id."""
    ids = sorted(item_ids)
    if not ids:
        return {}
    marker = _marker(conn)
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
        }
    return facts


def _delivery_environments(
    conn: Any, blocker_ids: Iterable[int], facts: Dict[int, Dict[str, Any]]
) -> Dict[int, Set[str]]:
    """Each blocker's reachable environments: any active flow of its project,
    plus the target of its own closing flow.

    A flow other than the closing one can still carry an item to its own
    environment as supplemental delivery, so only an environment no flow of
    the project reaches makes a ``fact:deployed`` edge impossible to clear.
    """
    ids = sorted(set(blocker_ids))
    if not ids:
        return {}
    targets = {
        str(row[0]): (int(row[1]), str(row[2] or ""), str(row[3] or ""))
        for row in conn.execute(
            "SELECT f.id, f.project_id, f.status, e.name FROM deployment_flows f "
            "LEFT JOIN environments e ON e.id = f.target_environment_id"
        ).fetchall()
    }
    by_project: Dict[int, Set[str]] = {}
    for project_id, status, environment in targets.values():
        if status == FLOW_STATUS_ACTIVE and environment:
            by_project.setdefault(project_id, set()).add(environment)
    closing = item_completion_flows(conn, ids)
    reachable: Dict[int, Set[str]] = {}
    for item_id in ids:
        project_id = facts.get(item_id, {}).get("project_id")
        environments = set(by_project.get(project_id, set()))
        own = targets.get(closing.get(item_id, ""))
        if own and own[2]:
            environments.add(own[2])
        reachable[item_id] = environments
    return reachable


def _deploying(conn: Any, item_id: int, environment: str) -> bool:
    marker = _marker(conn)
    terminal = tuple(sorted(TERMINAL_RUN_STATUSES))
    row = conn.execute(
        "SELECT 1 FROM deployment_run_items member "
        "JOIN deployment_runs run ON run.id = member.run_id "
        "JOIN deployment_flows flow ON flow.id = run.flow "
        "JOIN environments target ON target.id = "
        "COALESCE(run.target_environment_id, flow.target_environment_id) "
        f"WHERE member.item_id = {marker} AND target.name = {marker} "
        f"AND run.status NOT IN ({', '.join(marker for _ in terminal)}) LIMIT 1",
        (int(item_id), environment, *terminal),
    ).fetchone()
    return row is not None


def _environment(
    conn: Any,
    blocker_id: int,
    satisfaction: str,
    reachable: Set[str],
) -> Optional[Dict[str, Any]]:
    """Where the blocker stands in the environment the edge waits on."""
    environment = deployed_environment(satisfaction)
    if environment is None:
        return None
    fact = read_deployed_environment_fact(
        conn, blocking_item_id=blocker_id, satisfaction=satisfaction
    )
    if fact is None or not fact.registered:
        state = DELIVERY_UNREGISTERED
    elif fact.carried:
        state = DELIVERY_LIVE
    elif _deploying(conn, blocker_id, environment):
        state = DELIVERY_DEPLOYING
    else:
        state = DELIVERY_NOT_DEPLOYED
    return {
        "name": environment,
        "delivery_state": state,
        "in_delivery_flow": state == DELIVERY_LIVE
        or (state != DELIVERY_UNREGISTERED and environment in reachable),
    }


def frontier_dependency_edges(
    conn: Any, project_ids: Optional[Iterable[int]] = None
) -> List[Dict[str, Any]]:
    """Every unsatisfied blocking edge with a live dependent.

    ``project_ids`` keeps edges with either end in those projects, because a
    chain that crosses projects is one chain to the reader; ``None`` keeps all.
    """
    pending: List[tuple[str, BlockerDetail]] = []
    for gate_point in BLOCKING_GATE_POINTS:
        blocks = evaluate_batch_gates(conn, gate_point=gate_point, emit_events=False)
        for dependent_ref in sorted(blocks):
            pending.extend((dependent_ref, detail) for detail in blocks[dependent_ref])
    refs = {ref for ref, _ in pending} | {d.blocking_item for _, d in pending}
    ids = internal_ids_for_refs(conn, refs)
    facts = _item_facts(conn, set(ids.values()))
    scope = None if project_ids is None else {int(value) for value in project_ids}
    kept: List[tuple[str, BlockerDetail, int, int]] = []
    for dependent_ref, detail in pending:
        dependent_id = ids.get(dependent_ref)
        blocker_id = ids.get(detail.blocking_item)
        dependent = facts.get(dependent_id) if dependent_id is not None else None
        blocker = facts.get(blocker_id) if blocker_id is not None else None
        if dependent is None or blocker is None or dependent["terminal"]:
            continue
        if scope is not None and not (
            dependent["project_id"] in scope or blocker["project_id"] in scope
        ):
            continue
        kept.append((dependent_ref, detail, dependent_id, blocker_id))
    reachable = _delivery_environments(
        conn,
        (
            blocker_id
            for _, detail, _, blocker_id in kept
            if deployed_environment(detail.satisfaction)
        ),
        facts,
    )
    edges: List[Dict[str, Any]] = []
    for dependent_ref, detail, dependent_id, blocker_id in kept:
        dependent, blocker = facts[dependent_id], facts[blocker_id]
        edges.append(
            {
                "blocking_item": detail.blocking_item,
                "dependent_item": dependent_ref,
                "gate_point": detail.gate_point,
                "satisfaction": detail.satisfaction,
                "rationale": detail.rationale,
                "blocking_stage": blocker["status"],
                "blocking_terminal": blocker["terminal"],
                "blocking_title": blocker["title"],
                "blocking_project_id": blocker["project_id"],
                "blocking_project_sequence": blocker["project_sequence"],
                "dependent_project_id": dependent["project_id"],
                "dependent_project_sequence": dependent["project_sequence"],
                "environment": _environment(
                    conn,
                    blocker_id,
                    detail.satisfaction,
                    reachable.get(blocker_id, set()),
                ),
            }
        )
    return edges


__all__ = [
    "BLOCKING_GATE_POINTS",
    "DELIVERY_DEPLOYING",
    "DELIVERY_LIVE",
    "DELIVERY_NOT_DEPLOYED",
    "DELIVERY_UNREGISTERED",
    "FRONTIER_EDGE_FIELDS",
    "frontier_dependency_edges",
]
