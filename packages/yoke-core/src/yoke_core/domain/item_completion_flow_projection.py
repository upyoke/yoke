"""Read projections of the effective item flow and its durable source."""

from collections.abc import Mapping
from typing import Any, Iterable

from yoke_core.domain.deployment_item_flow_resolution import item_completion_flow_facts


def completion_flow_values(
    conn: Any, item_ids: Iterable[int]
) -> dict[int, dict[str, str]]:
    """``{value, source}`` per item, plus ``pinned`` when completion follows
    the stored pin's active successor rather than the pin itself."""
    values: dict[int, dict[str, str]] = {}
    for item_id, fact in item_completion_flow_facts(conn, item_ids).items():
        values[item_id] = {"value": fact.flow, "source": fact.source}
        if fact.pinned:
            values[item_id]["pinned"] = fact.pinned
    return values


def flow_id(field: Any) -> str:
    """The flow id an item read's ``deployment_flow`` field names.

    Item reads project the field as ``{value, source}``; a serving build that
    predates that projection returns the bare stored string. A client can
    meet either, so every consumer of an item read takes the id from here
    rather than stringifying the field.
    """
    if isinstance(field, Mapping):
        field = field.get("value")
    return str(field or "").strip()
