"""Attach each drawn card's effective completion flow to its overview row."""

from typing import Any

from yoke_core.domain.deployment_item_flow_resolution import (
    FLOW_SOURCE_NONE,
    item_completion_flow_facts,
)


def apply_effective_flows(conn: Any, drawn: list[dict[str, Any]]) -> None:
    """Put ``completion_flow`` and ``completion_flow_source`` on drawn rows.

    Delivery counts key off this flow so they stay on the same release line
    before and after a run pins the project default onto the item. A default
    that cannot be read is ``unreadable`` with an empty flow, never ``none``.
    """
    ids = [int(row["internal_id"]) for row in drawn]
    facts = item_completion_flow_facts(conn, ids)
    for row in drawn:
        fact = facts.get(int(row["internal_id"]))
        row["completion_flow"] = fact.flow if fact else ""
        row["completion_flow_source"] = (
            fact.source if fact else FLOW_SOURCE_NONE
        )


__all__ = ["apply_effective_flows"]
