"""Human rendering of item fields that carry effective flow provenance."""

from typing import Any


def render_item_field(value: Any) -> str:
    if isinstance(value, dict) and "value" in value and "source" in value:
        source = str(value["source"]).replace("_", " ")
        if value.get("pinned"):
            source += f"; follows retired pin {value['pinned']}"
        return f"{value['value'] or 'no completion flow'} ({source})"
    return "" if value is None else str(value)
