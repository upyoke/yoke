"""Where each blocker of a ``fact:deployed:<env>`` edge stands in that env.

One batched read per fact for the whole edge set, never one per edge: the
environments each blocker's project registers, the runs that carried a blocker
there or are carrying it now, and the environments any delivery flow can take
it to. The dependency kernel still decides whether the edge is satisfied; this
only explains an unsatisfied one to the reader.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional, Set, Tuple

from yoke_core.domain import db_backend
from yoke_core.domain.dependency_types import deployed_environment
from yoke_core.domain.deployment_flow_state import FLOW_STATUS_ACTIVE
from yoke_core.domain.deployment_item_flow_resolution import item_completion_flows
from yoke_core.domain.runs import TERMINAL_RUN_STATUSES

#: Where a blocker's delivery stands in the environment an edge waits on.
DELIVERY_LIVE = "live"
DELIVERY_DEPLOYING = "deploying"
DELIVERY_NOT_DEPLOYED = "not deployed"
DELIVERY_UNREGISTERED = "unregistered"


def _in(conn: Any, values: Iterable[Any]) -> Tuple[str, tuple]:
    values = tuple(values)
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    return ", ".join(marker for _ in values), values


def _run_memberships(
    conn: Any, item_ids: Tuple[int, ...], *, finished: bool
) -> Set[Tuple[int, str]]:
    """Completed attribution, or environments a live run is carrying."""
    if finished:
        from yoke_core.domain.completed_item_delivery import completed_deliveries

        return {
            (item_id, entry["environment"])
            for item_id, entries in completed_deliveries(conn, item_ids).items()
            for entry in entries
        }
    items, item_params = _in(conn, item_ids)
    terminal, terminal_params = _in(conn, sorted(TERMINAL_RUN_STATUSES))
    target = (
        "target.id = COALESCE(run.target_environment_id, flow.target_environment_id)"
    )
    status, status_params = f"run.status NOT IN ({terminal})", terminal_params
    rows = conn.execute(
        "SELECT DISTINCT member.item_id, target.name FROM deployment_run_items member "
        "JOIN deployment_runs run ON run.id = member.run_id "
        "JOIN deployment_flows flow ON flow.id = run.flow "
        f"JOIN environments target ON {target} "
        f"WHERE member.item_id IN ({items}) AND {status}",
        (*item_params, *status_params),
    ).fetchall()
    return {(int(row[0]), str(row[1])) for row in rows}


def _reachable(
    conn: Any, item_ids: Tuple[int, ...], projects: Dict[int, int]
) -> Dict[int, Set[str]]:
    """Each blocker's reachable environments: any active flow of its project,
    plus the target of its own closing flow.

    A flow other than the closing one can still carry an item to its own
    environment as supplemental delivery, so only an environment no flow of
    the project reaches makes a ``fact:deployed`` edge impossible to clear.
    """
    closing = item_completion_flows(conn, item_ids)
    project_ids, project_params = _in(conn, sorted(set(projects.values())))
    flow_ids = sorted({flow for flow in closing.values() if flow}) or [""]
    flows, flow_params = _in(conn, flow_ids)
    rows = conn.execute(
        "SELECT f.id, f.project_id, f.status, e.name FROM deployment_flows f "
        "JOIN environments e ON e.id = f.target_environment_id "
        f"WHERE (f.status = '{FLOW_STATUS_ACTIVE}' AND f.project_id IN ({project_ids})) "
        f"OR f.id IN ({flows})",
        (*project_params, *flow_params),
    ).fetchall()
    by_project: Dict[int, Set[str]] = {}
    by_flow: Dict[str, str] = {}
    for flow_id, project_id, status, environment in rows:
        by_flow[str(flow_id)] = str(environment)
        if status == FLOW_STATUS_ACTIVE:
            by_project.setdefault(int(project_id), set()).add(str(environment))
    reachable: Dict[int, Set[str]] = {}
    for item_id in item_ids:
        environments = set(by_project.get(projects[item_id], set()))
        own = by_flow.get(closing.get(item_id, ""))
        if own:
            environments.add(own)
        reachable[item_id] = environments
    return reachable


def edge_environments(
    conn: Any, wanted: Iterable[Tuple[int, str]], projects: Dict[int, int]
) -> Dict[Tuple[int, str], Optional[Dict[str, Any]]]:
    """The ``environment`` object for each (blocker id, satisfaction) pair.

    ``projects`` maps each blocker id to its project id. Pairs whose
    satisfaction names no environment answer None.
    """
    pairs = {
        (int(item_id), str(satisfaction))
        for item_id, satisfaction in wanted
        if deployed_environment(str(satisfaction))
    }
    if not pairs:
        return {}
    item_ids = tuple(sorted({item_id for item_id, _ in pairs}))
    project_ids, project_params = _in(conn, sorted({projects[i] for i in item_ids}))
    registered = {
        (int(row[0]), str(row[1]))
        for row in conn.execute(
            f"SELECT project_id, name FROM environments WHERE project_id IN ({project_ids})",
            project_params,
        ).fetchall()
    }
    carried = _run_memberships(conn, item_ids, finished=True)
    deploying = _run_memberships(conn, item_ids, finished=False)
    reachable = _reachable(conn, item_ids, projects)
    answers: Dict[Tuple[int, str], Optional[Dict[str, Any]]] = {}
    for item_id, satisfaction in pairs:
        environment = str(deployed_environment(satisfaction))
        if (projects[item_id], environment) not in registered:
            state = DELIVERY_UNREGISTERED
        elif (item_id, environment) in carried:
            state = DELIVERY_LIVE
        elif (item_id, environment) in deploying:
            state = DELIVERY_DEPLOYING
        else:
            state = DELIVERY_NOT_DEPLOYED
        answers[(item_id, satisfaction)] = {
            "name": environment,
            "delivery_state": state,
            "in_delivery_flow": state == DELIVERY_LIVE
            or (state != DELIVERY_UNREGISTERED and environment in reachable[item_id]),
        }
    return answers


__all__ = [
    "DELIVERY_DEPLOYING",
    "DELIVERY_LIVE",
    "DELIVERY_NOT_DEPLOYED",
    "DELIVERY_UNREGISTERED",
    "edge_environments",
]
