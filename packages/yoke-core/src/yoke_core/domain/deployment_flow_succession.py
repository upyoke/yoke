"""Follow a retired deployment flow to the active flow that replaced it.

A flow a run has referenced is immutable, so changing it means publishing a
successor (``supersedes_flow_id``) and disabling the predecessor. Items keep
their stored pin; completion authority follows the pin's recorded successor
so the retirement does not strand them.
"""

from typing import Any, Iterable

from yoke_contracts.timestamps import parse_instant
from yoke_core.domain import db_backend
from yoke_core.domain.deployment_flow_state import FLOW_STATUS_ACTIVE
from yoke_core.domain.schema_common import _column_exists


def succession_chains(conn: Any, flow_ids: Iterable[str]) -> dict[str, tuple[str, ...]]:
    """Map each named flow to its supersession chain, pin first.

    An active flow, or one this database does not know, is a one-flow chain.
    A flow that is no longer active chains through ``supersedes_flow_id`` to
    the newest active flow among everything that supersedes it, directly or
    transitively, within the same project and to the same delivery target:
    a successor whose target environment or tier differs from its
    predecessor's (a stage or QA-only flow succeeding a production one) does
    not deliver that predecessor's items, so it is not followed. With no
    such active successor it stays
    a one-flow chain, so the caller's existing no-active-flow refusal still
    names the retired pin. Every flow on a chain carried the pin's items at
    some point, so a delivery on any of them is that item's delivery.
    """
    wanted = tuple(dict.fromkeys(str(f).strip() for f in flow_ids if str(f).strip()))
    chains = {flow_id: (flow_id,) for flow_id in wanted}
    if not wanted or not _column_exists(conn, "deployment_flows", "supersedes_flow_id"):
        return chains
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    target = ", ".join(
        f"COALESCE(CAST({column} AS TEXT), '')"
        if _column_exists(conn, "deployment_flows", column)
        else "''"
        for column in ("target_environment_id", "target_tier")
    )
    rows = conn.execute(
        "SELECT id, project_id, status, supersedes_flow_id, "
        f"created_at, {target} "
        "FROM deployment_flows WHERE project_id IN ("
        "SELECT project_id FROM deployment_flows "
        f"WHERE id IN ({','.join(marker for _ in wanted)}))",
        wanted,
    ).fetchall()
    flows = {
        str(row[0]): (
            row[1],
            str(row[2] or ""),
            row[4],
            (row[5], row[6]),
        )
        for row in rows
    }
    predecessor: dict[str, str] = {}
    successors: dict[str, list[str]] = {}
    for row in rows:
        source = str(row[3] or "").strip()
        if (
            source in flows
            and flows[source][0] == row[1]
            and flows[source][3] == (row[5], row[6])
        ):
            predecessor[str(row[0])] = source
            successors.setdefault(source, []).append(str(row[0]))
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
        if not active:
            continue
        chain = [
            max(
                active,
                key=lambda f: (
                    flows[f][2] is not None,
                    parse_instant(flows[f][2]) if flows[f][2] is not None else None,
                    f,
                ),
            )
        ]
        while chain[-1] != flow_id:
            chain.append(predecessor[chain[-1]])
        chains[flow_id] = tuple(reversed(chain))
    return chains


def successor_flows(conn: Any, flow_ids: Iterable[str]) -> dict[str, str]:
    """Map each named flow to the flow that now carries its items.

    The last flow of its :func:`succession_chains` chain.
    """
    return {
        flow_id: chain[-1]
        for flow_id, chain in succession_chains(conn, flow_ids).items()
    }


__all__ = ["succession_chains", "successor_flows"]
