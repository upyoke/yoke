"""Structured API adapter inventory for workflow version operators."""

from yoke_core.api.service_client_structured_api_adapter_inventory_types import (
    AdapterEntry,
    read_entry,
)

WORKFLOW_ADAPTERS = [
    AdapterEntry(
        function_id="workflows.version.publish",
        cli_invocation="yoke workflows version publish WORKFLOW --definition-file F --reason TEXT "
        "[--expected-current-version N] [--keep-current] [--session-id S] [--json]",
        notes="Publishes a full immutable definition; append-only preserves the default and canon-follow.",
    ),
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
        function_id="workflows.version.list",
        cli_invocation=(
            "yoke workflows version list [WORKFLOW] [--session-id S] [--json]"
        ),
        notes="Lists published immutable versions, optionally for one workflow.",
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
            "yoke workflows item migrate ITEM [--version N] [--preview] "
            "[--project P] [--session-id S] [--json]"
        ),
        notes="Previews or migrates an existing item to another published version.",
    ),
    AdapterEntry(
        function_id="workflows.item_posture.amend",
        cli_invocation=(
            "yoke workflows item-posture amend ITEM --reason TEXT "
            "(--verification-plan ID_OR_SLUG | --verification-method ID | "
            "--key KEY (--value JSON | --clear)) "
            "[--project P] [--session-id S] [--json]"
        ),
        notes="Sets, replaces, or clears one posture key on a filed item.",
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
    read_entry(
        function_id="workflows.canon_status.list",
        cli_invocation=(
            "yoke workflows canon-status list [--pending] [--session-id S] [--json]"
        ),
        notes="Where each built-in workflow stands against its published canon.",
    ),
    read_entry(
        function_id="workflows.canon_update.preview",
        cli_invocation=(
            "yoke workflows canon-update preview WORKFLOW [--session-id S] [--json]"
        ),
        notes="Shows the merge a take would publish: taken, kept, conflicts.",
    ),
    AdapterEntry(
        function_id="workflows.canon_update.apply",
        cli_invocation=(
            "yoke workflows canon-update apply WORKFLOW "
            "--expected-current-version N [--session-id S] [--json]"
        ),
        notes="Takes the newest published generation, preserving local edits.",
    ),
    AdapterEntry(
        function_id="workflows.canon_update.apply_all",
        cli_invocation=(
            "yoke workflows canon-update apply-all WORKFLOW=VERSION "
            "[WORKFLOW=VERSION ...] [--session-id S] [--json]"
        ),
        notes="Takes several published updates, reporting each entry on its own.",
    ),
    AdapterEntry(
        function_id="workflows.canon_follow.set",
        cli_invocation=(
            "yoke workflows canon-follow set WORKFLOW (auto|manual) "
            "[--session-id S] [--json]"
        ),
        notes="Chooses whether new published generations arrive by themselves.",
    ),
    AdapterEntry(
        function_id="workflow.execution_instruction.create",
        cli_invocation=(
            "yoke workflow execution-instruction create "
            "(--content C | --stdin) [--json]"
        ),
    ),
    AdapterEntry(
        function_id="workflow.execution_instruction.update",
        cli_invocation=(
            "yoke workflow execution-instruction update ID "
            "(--content C | --stdin) [--json]"
        ),
    ),
    AdapterEntry(
        function_id="workflow.execution_instruction.set_scope",
        cli_invocation=(
            "yoke workflow execution-instruction set-scope ID "
            "[--all-workflows] [--workflow W ...] "
            "[--all-projects] [--project-id N ...] "
            "[--before-creation | --no-before-creation] "
            "[--on-every-read | --no-on-every-read] "
            "[--when-entering-stage | --no-when-entering-stage] "
            "[--stage-bucket B ... | --clear-stage-buckets] [--json]"
        ),
        notes="Replaces the instruction's workflow and project bindings.",
    ),
    read_entry(
        function_id="workflow.execution_instruction.resolve",
        cli_invocation=(
            "yoke workflow execution-instruction resolve "
            "--workflow W --project P [--delivery-point POINT] [--stage-bucket B] [--full] [--json]"
        ),
        notes="Only instructions matching the named workflow and project.",
    ),
    read_entry(
        function_id="workflow.execution_instruction.list",
        cli_invocation="yoke workflow execution-instruction list [--json]",
        notes="Every instruction with its workflow/project scope.",
    ),
    AdapterEntry(
        function_id="workflow.execution_instruction.delete",
        cli_invocation="yoke workflow execution-instruction delete ID [--json]",
    ),
]

__all__ = ["WORKFLOW_ADAPTERS"]
