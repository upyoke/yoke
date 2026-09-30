"""Read projections of the effective item flow and its durable source."""

from typing import Any, Iterable

from yoke_core.domain.deployment_item_flow_resolution import item_completion_flow_facts


def completion_flow_values(
    conn: Any, item_ids: Iterable[int]
) -> dict[int, dict[str, str]]:
    return {
        item_id: {"value": fact.flow, "source": fact.source}
        for item_id, fact in item_completion_flow_facts(conn, item_ids).items()
    }
