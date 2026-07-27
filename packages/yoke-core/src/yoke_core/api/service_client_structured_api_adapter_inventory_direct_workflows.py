"""Structured API adapter inventory for direct-workflow execution."""

from yoke_core.api.service_client_structured_api_adapter_inventory_types import (
    AdapterEntry,
)


DIRECT_WORKFLOW_ADAPTERS = [
    AdapterEntry(
        function_id="direct_workflow.dash.survey",
        cli_invocation=(
            "yoke direct-workflow dash survey ITEM --path PATH "
            "[--integration-target BRANCH]"
        ),
    ),
    AdapterEntry(
        function_id="direct_workflow.blitz.survey",
        cli_invocation=(
            "yoke direct-workflow blitz survey ITEM --path PATH "
            "[--integration-target BRANCH]"
        ),
    ),
    AdapterEntry(
        function_id="direct_workflow.dash.evidence",
        cli_invocation=(
            "yoke direct-workflow dash evidence ITEM --result TEXT "
            "--verification TEXT --commit-sha SHA --merge-sha SHA"
        ),
    ),
    AdapterEntry(
        function_id="direct_workflow.dash.escalate",
        cli_invocation=(
            "yoke direct-workflow dash escalate ITEM --issue-title TITLE "
            "--findings TEXT"
        ),
    ),
    AdapterEntry(
        function_id="ouroboros.field_note.promote",
        cli_invocation=(
            "yoke ouroboros field-note promote ENTRY --title TITLE"
        ),
    ),
]


__all__ = ["DIRECT_WORKFLOW_ADAPTERS"]
