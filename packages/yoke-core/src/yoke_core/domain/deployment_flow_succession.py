"""Follow a retired deployment flow to the active flow that replaced it.

A flow a run has referenced is immutable, so changing it means publishing a
successor (``supersedes_flow_id``) and disabling the predecessor. Items keep
their stored pin; completion authority follows the pin's recorded successor
so the retirement does not strand them.
"""

from typing import Any, Iterable

from yoke_core.domain import db_backend
from yoke_core.domain.deployment_flow_state import FLOW_STATUS_ACTIVE
from yoke_core.domain.schema_common import _column_exists


def successor_flows(conn: Any, flow_ids: Iterable[str]) -> dict[str, str]:
    """Map each named flow to the flow that now carries its items.

    An active flow, or one this database does not know, maps to itself. A
    flow that is no longer active maps to the newest active flow among
    everything that supersedes it, directly or through a chain of
    successors, within the same project. With no active successor it maps
    to itself, so the caller's existing no-active-flow refusal still names
    the retired pin.
    """
    wanted = tuple(dict.fromkeys(str(f).strip() for f in flow_ids if str(f).strip()))
    if not wanted:
        return {}
    resolved = {flow_id: flow_id for flow_id in wanted}
    if not _column_exists(conn, "deployment_flows", "supersedes_flow_id"):
        return resolved
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    rows = conn.execute(
        "SELECT id, project_id, status, supersedes_flow_id, "
        "COALESCE(created_at, '') FROM deployment_flows WHERE project_id IN ("
        "SELECT project_id FROM deployment_flows "
        f"WHERE id IN ({','.join(marker for _ in wanted)}))",
        wanted,
    ).fetchall()
    flows = {
        str(row[0]): (row[1], str(row[2] or ""), str(row[4] or "")) for row in rows
    }
    successors: dict[str, list[str]] = {}
    for row in rows:
        predecessor = str(row[3] or "").strip()
        if predecessor and predecessor in flows and flows[predecessor][0] == row[1]:
            successors.setdefault(predecessor, []).append(str(row[0]))
    for flow_id in wanted:
        known = flows.get(flow_id)
        if known is None or known[1] == FLOW_STATUS_ACTIVE:
            continue
        seen = {flow_id}
        frontier = list(successors.get(flow_id, ()))
        active: list[str] = []
        while frontier:
            current = frontier.pop()
            if current in seen:
                continue
            seen.add(current)
            if flows[current][1] == FLOW_STATUS_ACTIVE:
                active.append(current)
            frontier.extend(successors.get(current, ()))
        if active:
            resolved[flow_id] = max(active, key=lambda f: (flows[f][2], f))
    return resolved


__all__ = ["successor_flows"]
