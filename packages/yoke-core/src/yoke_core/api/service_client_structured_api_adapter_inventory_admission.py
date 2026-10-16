"""CLI entry points for personal machine admission and API tokens."""

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
    AdapterEntry(
        function_id="profile.token.create",
        cli_invocation="yoke tokens create --name LABEL [--json]",
        notes="Creates your own token and shows it once; revoke and create again if lost.",
    ),
    read_entry(
        function_id="profile.get",
        cli_invocation="yoke tokens list [--json]",
        notes="Lists your non-secret token metadata.",
    ),
    AdapterEntry(
        function_id="profile.token.revoke",
        cli_invocation="yoke tokens revoke TOKEN-ID [--json]",
    ),
]
