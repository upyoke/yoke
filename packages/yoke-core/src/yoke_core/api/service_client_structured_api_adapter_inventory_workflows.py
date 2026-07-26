"""Structured API adapter inventory for workflow version operators."""

from yoke_core.api.service_client_structured_api_adapter_inventory_types import (
    AdapterEntry,
    read_entry,
)

WORKFLOW_ADAPTERS = [
    read_entry(
        function_id="workflows.definition.get",
        cli_invocation="yoke workflows definition get [--workflow ID] [--version N]",
        notes="Reads authoritative immutable workflow definitions and current selection.",
    ),
    read_entry(
        function_id="workflows.version.get",
        cli_invocation="yoke workflows version get WORKFLOW VERSION",
        notes="Reads one immutable version, including its complete definition.",
    ),
    read_entry(
        function_id="workflows.item.get",
        cli_invocation="yoke workflows item get YOK-N",
        notes="Inspects the immutable workflow version pinned by an item.",
    ),
    AdapterEntry(
        function_id="workflows.current.set",
        cli_invocation="yoke workflows current set WORKFLOW VERSION",
        notes="Selects the published version used only by newly created items.",
    ),
    AdapterEntry(
        function_id="workflows.policy_defaults.publish",
        cli_invocation=(
            "yoke workflows policy-defaults publish WORKFLOW "
            "--path-claims on|off --expected-current-version N"
        ),
        notes="Publishes a new immutable version from constrained policy defaults.",
    ),
    AdapterEntry(
        function_id="workflows.item.migrate",
        cli_invocation="yoke workflows item migrate YOK-N --to-version N",
        notes="Explicitly migrates a compatible existing item to another published version.",
    ),
]

__all__ = ["WORKFLOW_ADAPTERS"]
