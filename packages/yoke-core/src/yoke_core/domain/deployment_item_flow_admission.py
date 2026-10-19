"""Check and pin the completion flow of every item a run admits, as one set.

Admission refuses an item whose closing flow cannot be resolved, and pins
the live project default onto an item with no explicit flow: membership is
the last write before a run can ship the item, so a later project-default
change cannot retarget completion authority for an already-admitted item.

Both questions are answered for the whole admitted set from one
:func:`~yoke_core.domain.deployment_item_flow_resolution.item_completion_flow_facts`
read, so admitting many members costs the same round trips as admitting one.
"""

from typing import Any, Iterable

from yoke_core.domain.deployment_item_flow_resolution import (
    FLOW_SOURCE_ITEM,
    FLOW_SOURCE_UNREADABLE,
    item_completion_flow_facts,
)
from yoke_core.domain.item_ref_render import render_item_ref_lookup
from yoke_core.domain.schema_common import _column_exists


def completion_flow_refusals(conn: Any, item_ids: Iterable[int]) -> dict[int, str]:
    """Explain why each delivery-ready item cannot enter a release composition.

    Items with a resolvable completion flow are absent from the result.
    """
    ids = tuple(dict.fromkeys(int(value) for value in item_ids))
    facts = item_completion_flow_facts(conn, ids)
    failing = [
        item_id for item_id in ids if not getattr(facts.get(item_id), "flow", "")
    ]
    if not failing:
        return {}
    ref = render_item_ref_lookup(conn, failing)
    refusals: dict[int, str] = {}
    for item_id in failing:
        fact = facts.get(item_id)
        if fact and fact.source == FLOW_SOURCE_UNREADABLE:
            refusals[item_id] = (
                f"{ref(item_id)} completion flow is unreadable; repair its project "
                "workflow delivery default, then retry the deployment start"
            )
    unexplained = [item_id for item_id in failing if item_id not in refusals]
    if not unexplained:
        return refusals
    if not _column_exists(conn, "items", "workflow_id"):
        return refusals | {
            item_id: (
                f"{ref(item_id)} completion flow cannot be resolved because "
                "items.workflow_id has not converged; converge the item schema, "
                "then retry the deployment start"
            )
            for item_id in unexplained
        }
    rows = conn.execute(
        "SELECT i.id,p.slug,i.workflow_id FROM items i JOIN projects p "
        "ON p.id=i.project_id WHERE i.id=ANY(%s)",
        (unexplained,),
    ).fetchall()
    for row in rows:
        refusals[int(row["id"])] = (
            f"{ref(row['id'])} has no resolvable completion flow; select one "
            f"with yoke workflows delivery-default set --project {row['slug']} "
            f"--workflow {row['workflow_id']} --flow FLOW, then retry the "
            "deployment start"
        )
    return refusals


def freeze_item_completion_flows(conn: Any, item_ids: Iterable[int]) -> dict[int, str]:
    """Pin the live default onto every item with no explicit flow.

    Returns each item's stored flow afterwards: its own pin, the default just
    pinned, or ``""`` when neither exists.
    """
    facts = item_completion_flow_facts(conn, item_ids)
    frozen: dict[int, str] = {}
    pins: dict[int, str] = {}
    for item_id, fact in facts.items():
        if fact.source == FLOW_SOURCE_ITEM:
            frozen[item_id] = fact.pinned or fact.flow
        elif fact.flow:
            frozen[item_id] = pins[item_id] = fact.flow
        else:
            frozen[item_id] = ""
    if pins:
        conn.execute(
            "UPDATE items SET deployment_flow=pin.flow "
            "FROM unnest(%s::bigint[], %s::text[]) AS pin(id, flow) "
            "WHERE items.id=pin.id AND COALESCE(items.deployment_flow,'')=''",
            (list(pins), list(pins.values())),
        )
    return frozen


__all__ = ["completion_flow_refusals", "freeze_item_completion_flows"]
