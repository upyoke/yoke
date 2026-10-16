"""CLI entry points for personal machine admission."""

from typing import List

from yoke_core.api.service_client_structured_api_adapter_inventory_types import (
    AdapterEntry,
    read_entry,
)

ADMISSION_ADAPTERS: List[AdapterEntry] = [
    read_entry(
        function_id="machine_authorization.pending",
        cli_invocation="yoke machines pending [--json]",
    ),
    read_entry(
        function_id="machine_authorization.get",
        cli_invocation="yoke machines approve CODE [--json]",
        notes="Reads the machine and signed-in identity before approve or deny.",
    ),
    AdapterEntry(
        function_id="machine_authorization.resolve",
        cli_invocation="yoke machines approve CODE [--json]",
        notes="Use yoke machines deny CODE to refuse the request.",
    ),
]
