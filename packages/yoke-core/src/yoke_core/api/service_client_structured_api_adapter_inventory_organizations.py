"""Organization identity and settings structured CLI adapters."""

from yoke_core.api.service_client_structured_api_adapter_inventory_types import (
    AdapterEntry,
    read_entry,
)


ORGANIZATION_ADAPTERS = [
    read_entry(
        function_id="organizations.get",
        cli_invocation="yoke organizations get",
    ),
    read_entry(
        function_id="organizations.settings.get",
        cli_invocation="yoke settings get membership.auto_join_domain_verified",
    ),
    AdapterEntry(
        function_id="organizations.settings.merge",
        cli_invocation="yoke settings set membership.auto_join_domain_verified true",
    ),
    AdapterEntry(
        function_id="organizations.create",
        cli_invocation="yoke organizations create NAME --slug SLUG",
        notes="hosted only: Platform founds the org on a machine's hosted connection",
    ),
    AdapterEntry(
        function_id="organizations.domain.set",
        cli_invocation="yoke organizations domain set DOMAIN",
    ),
]

__all__ = ["ORGANIZATION_ADAPTERS"]
