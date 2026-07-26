"""Structured API adapter inventory for Test Mac operations."""

from yoke_core.api.service_client_structured_api_adapter_inventory_types import (
    AdapterEntry,
    read_entry,
)


TEST_MACHINE_ADAPTERS = [
    read_entry(
        function_id="test_machine.get",
        cli_invocation="yoke test-machine get --project P",
    ),
    AdapterEntry(
        function_id="test_machine.settings_replace",
        cli_invocation=(
            "yoke test-machine settings-replace --project P "
            "--settings-file FILE --base AS_READ_JSON"
        ),
    ),
    AdapterEntry(
        function_id="test_machine.verify",
        cli_invocation="yoke test-machine verify --project P",
    ),
]


__all__ = ["TEST_MACHINE_ADAPTERS"]
