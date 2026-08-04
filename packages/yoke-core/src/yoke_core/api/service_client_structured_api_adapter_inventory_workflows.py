"""Structured API adapter inventory for workflow version operators."""

from yoke_core.api.service_client_structured_api_adapter_inventory_types import (
    AdapterEntry,
    read_entry,
)

WORKFLOW_ADAPTERS = [
    read_entry(
        function_id="workflows.definition.get",
        cli_invocation=(
            "yoke workflows definition get [--project P] [--session-id S] [--json]"
        ),
        notes="Reads authoritative immutable workflow definitions and current selection.",
    ),
    read_entry(
        function_id="workflows.version.get",
        cli_invocation=(
            "yoke workflows version get WORKFLOW VERSION [--session-id S] [--json]"
        ),
        notes="Reads one immutable version, including its complete definition.",
    ),
    read_entry(
        function_id="workflows.item.get",
        cli_invocation=(
            "yoke workflows item get ITEM [--project P] [--session-id S] [--json]"
        ),
        notes="Inspects the immutable workflow version pinned by an item.",
    ),
    AdapterEntry(
        function_id="workflows.current.set",
        cli_invocation=(
            "yoke workflows current set WORKFLOW VERSION "
            "[--expected-current-version N] [--session-id S] [--json]"
        ),
        notes="Selects the published version used only by newly created items.",
    ),
    AdapterEntry(
        function_id="workflows.policy_defaults.publish",
        cli_invocation=(
            "yoke workflows policy-defaults publish WORKFLOW "
            "(--file-budget on|off | --path-claims on|off | "
            "--path-survey on|off) "
            "--expected-current-version N "
            "[--session-id S] [--json]"
        ),
        notes="Publishes a new immutable version from constrained policy defaults.",
    ),
    AdapterEntry(
        function_id="workflows.item.migrate",
        cli_invocation=(
            "yoke workflows item migrate ITEM [--version N] [--project P] "
            "[--session-id S] [--json]"
        ),
        notes="Explicitly migrates a compatible existing item to another published version.",
    ),
    read_entry(
        function_id="workflows.mechanics.get",
        cli_invocation="yoke workflows mechanics get [--json]",
        notes="Reads project defaults and the named approver roster.",
    ),
    AdapterEntry(
        function_id="workflows.testing_default.set",
        cli_invocation=(
            "yoke workflows testing-default set --project P --workflow W "
            "--plan-id N [--apply-to-all] [--json]"
        ),
    ),
    AdapterEntry(
        function_id="workflows.delivery_default.set",
        cli_invocation=(
            "yoke workflows delivery-default set --project P --workflow W "
            "--flow F [--apply-to-all] [--json]"
        ),
    ),
    AdapterEntry(
        function_id="workflows.approval_defaults.publish",
        cli_invocation=(
            "yoke workflows approval-defaults publish --workflow W "
            "--expected-current-version N --defaults-file FILE [--json]"
        ),
        notes="Publishes a new immutable version with bounded approval defaults.",
    ),
]

__all__ = ["WORKFLOW_ADAPTERS"]
