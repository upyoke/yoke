"""Item-family entries for the structured API adapter inventory."""

from __future__ import annotations

from yoke_core.api.service_client_structured_api_adapter_inventory_types import (
    AdapterEntry,
)


ITEMS_ADAPTERS = [
    AdapterEntry(
        function_id="items.scalar.update",
        cli_invocation=(
            "python3 -m yoke_core.cli.db_router items update YOK-N "
            "<field> <value>"
        ),
    ),
    AdapterEntry(
        function_id="items.github_sync",
        cli_invocation="yoke items github-sync YOK-N",
        notes=(
            "Backlog GitHub item/epic sync; registered agent surface is "
            "yoke items github-sync YOK-N."
        ),
    ),
]


__all__ = ["ITEMS_ADAPTERS"]
