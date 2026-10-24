"""CLI entry points for people, machines and API tokens."""

from typing import List

from yoke_core.api.service_client_structured_api_adapter_inventory_types import (
    AdapterEntry,
    read_entry,
)

ADMISSION_ADAPTERS: List[AdapterEntry] = [
    read_entry(
        function_id="machine_authorization.pending",
        cli_invocation=("yoke machines pending [--json] [--session-id S]"),
    ),
    read_entry(
        function_id="machine_authorization.get",
        cli_invocation=("yoke machines approve CODE [--session-id S] [--json]"),
        notes="Reads the machine and signed-in identity before approve or deny.",
    ),
    AdapterEntry(
        function_id="machine_authorization.resolve",
        cli_invocation=(
            "yoke machines approve CODE [--session-id S] [--json] | yoke machines "
            "deny CODE [--session-id S] [--json]"
        ),
        notes="Use yoke machines deny CODE to refuse the request.",
    ),
    AdapterEntry(
        function_id="profile.token.create",
        cli_invocation=("yoke tokens create --name LABEL [--json] [--session-id S]"),
        notes="Creates your own token and shows it once; revoke and create again if lost.",
    ),
    read_entry(
        function_id="profile.get",
        cli_invocation=("yoke tokens list [--json] [--session-id S]"),
        notes="Lists your non-secret token metadata.",
    ),
    AdapterEntry(
        function_id="profile.token.revoke",
        cli_invocation=("yoke tokens revoke TOKEN-ID [--json] [--session-id S]"),
    ),
    AdapterEntry(
        function_id="teammate_invites.create",
        cli_invocation=("yoke invite PERSON [--role ROLE] [--json] [--session-id S]"),
    ),
    read_entry(
        function_id="teammate_invites.list",
        cli_invocation=("yoke invites list [--include-used] [--json] [--session-id S]"),
    ),
    AdapterEntry(
        function_id="teammate_invites.revoke",
        cli_invocation=("yoke invites revoke REF [--json] [--session-id S]"),
    ),
    AdapterEntry(
        function_id="teammate_invites.reissue",
        cli_invocation=("yoke invites reissue REF [--json] [--session-id S]"),
    ),
    AdapterEntry(
        function_id="identity.invite.create",
        cli_invocation=("yoke invite PERSON [--role ROLE] [--json] [--session-id S]"),
    ),
    read_entry(
        function_id="identity.invite.list",
        cli_invocation=("yoke invites list [--include-used] [--json] [--session-id S]"),
    ),
    AdapterEntry(
        function_id="identity.invite.revoke",
        cli_invocation=("yoke invites revoke REF [--json] [--session-id S]"),
    ),
]
