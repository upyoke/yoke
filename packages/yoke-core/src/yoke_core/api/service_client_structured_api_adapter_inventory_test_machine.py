"""Structured API adapter inventory for Test Mac operations."""

from yoke_core.api.service_client_structured_api_adapter_inventory_types import (
    AdapterEntry,
    read_entry,
)


TEST_MACHINE_ADAPTERS = [
    read_entry(
        function_id="test_machine.list",
        cli_invocation="yoke test-machine list --project P",
    ),
    read_entry(
        function_id="test_machine.get",
        cli_invocation="yoke test-machine get --project P --machine NAME",
    ),
    AdapterEntry(
        function_id="test_machine.settings_replace",
        cli_invocation=(
            "yoke test-machine settings-replace --project P "
            "--machine NAME --settings-file FILE --base AS_READ_JSON"
        ),
    ),
    AdapterEntry(
        function_id="test_machine.verify",
        cli_invocation="yoke test-machine verify --project P --machine NAME",
    ),
    AdapterEntry(
        function_id="test_machine.reset",
        cli_invocation=(
            "yoke test-machine reset --project P --machine NAME --baseline fresh-host"
        ),
    ),
    AdapterEntry(
        function_id="test_machine.golden_capture",
        cli_invocation=("yoke test-machine golden-capture --project P --machine NAME"),
    ),
    AdapterEntry(
        function_id="test_machine.bridge_diagnose",
        cli_invocation=("yoke test-machine bridge-diagnose --project P --machine NAME"),
    ),
]


__all__ = ["TEST_MACHINE_ADAPTERS"]
