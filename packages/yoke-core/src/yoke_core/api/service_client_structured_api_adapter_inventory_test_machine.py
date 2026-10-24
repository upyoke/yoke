"""Structured API adapter inventory for Test Machine operations."""

from yoke_core.api.service_client_structured_api_adapter_inventory_types import (
    AdapterEntry,
    read_entry,
)


TEST_MACHINE_ADAPTERS = [
    AdapterEntry(
        function_id="test_machine.desktop_access",
        cli_invocation=(
            "yoke test-machine desktop-access --project P "
            "--test-machine TEST_MACHINE [--view] [--session-id S]"
        ),
    ),
    read_entry(
        function_id="test_machine.list",
        cli_invocation=("yoke test-machine list --project P [--json] [--session-id S]"),
    ),
    read_entry(
        function_id="test_machine.get",
        cli_invocation=(
            "yoke test-machine get --project P "
            "[--test-machine TEST_MACHINE] [--json] "
            "[--session-id S]"
        ),
    ),
    AdapterEntry(
        function_id="test_machine.settings_replace",
        cli_invocation=(
            "yoke test-machine settings-replace --project P "
            "[--test-machine TEST_MACHINE] --settings-file FILE (--base "
            "AS_READ_JSON | --new) [--json] [--session-id S]"
        ),
    ),
    AdapterEntry(
        function_id="test_machine.verify",
        cli_invocation=(
            "yoke test-machine verify --project P [--test-machine "
            "TEST_MACHINE] [--json] [--session-id S]"
        ),
    ),
    AdapterEntry(
        function_id="test_machine.reset",
        cli_invocation=(
            "yoke test-machine reset --project P [--test-machine "
            "TEST_MACHINE] [--baseline fresh-host|shell-preconfigured] "
            "[--json] [--session-id S]"
        ),
    ),
    AdapterEntry(
        function_id="test_machine.golden_capture",
        cli_invocation=(
            "yoke test-machine golden-capture --project P "
            "[--test-machine TEST_MACHINE] [--destination /abs/path] "
            "[--probes-file FILE] [--json] [--session-id S]"
        ),
    ),
    AdapterEntry(
        function_id="test_machine.bridge_diagnose",
        cli_invocation=(
            "yoke test-machine bridge-diagnose --project P "
            "[--test-machine TEST_MACHINE] [--json] [--session-id S]"
        ),
    ),
    AdapterEntry(
        function_id="test_machine.screenshot",
        cli_invocation=(
            "yoke test-machine screenshot --project P [--test-machine "
            "TEST_MACHINE] [--json] [--session-id S]"
        ),
    ),
]


__all__ = ["TEST_MACHINE_ADAPTERS"]
