"""Structured adapter inventory entries for epic workflow commands."""

from __future__ import annotations

from typing import List

from yoke_core.api.service_client_structured_api_adapter_inventory_types import (
    AdapterEntry,
    read_entry as _read_entry,
)


EPIC_ADAPTERS: List[AdapterEntry] = [
    AdapterEntry(
        "workflow_item.epic_task.body_replace",
        "yoke workflow-item epic-task body-replace --epic N --task-num N --body-file PATH",
        notes="Epic task body replace.",
    ),
    AdapterEntry(
        "workflow_item.epic_task.metadata_update",
        "yoke workflow-item epic-task metadata-update --epic N --task-num N --fields-json JSON",
    ),
    AdapterEntry(
        "workflow_item.epic_task.add",
        "yoke workflow-item epic-task add --epic N --title TEXT",
    ),
    AdapterEntry(
        "workflow_item.epic_task.remove",
        "yoke workflow-item epic-task remove --epic N --task-num N",
    ),
    AdapterEntry(
        "workflow_item.epic_task.reassign",
        "yoke workflow-item epic-task reassign --epic N --task-num N --new-worktree NAME",
    ),
    AdapterEntry(
        "workflow_item.epic_task.split",
        "yoke workflow-item epic-task split --epic N --task-num N --children-json JSON",
    ),
    _read_entry(
        function_id="workflow_item.epic_task.get",
        cli_invocation="yoke workflow-item epic-task get --epic N --task-num N",
    ),
    _read_entry(
        function_id="workflow_item.epic_task.body_get",
        cli_invocation="yoke workflow-item epic-task body-get --epic N --task-num N [--output-file PATH]",
    ),
    AdapterEntry(
        "workflow_item.epic_task.update_status",
        "yoke workflow-item epic-task update-status --epic N --task-num N --status STATUS",
    ),
    AdapterEntry(
        "conduct.epic_task.update_status",
        "yoke conduct epic-task update-status --epic N --task-num N --status STATUS",
        notes="Full conduct status pipeline; unlike workflow_item.epic_task.update_status, this route runs update_status side effects.",
    ),
    AdapterEntry(
        "workflow_item.epic_task.file_add",
        "yoke workflow-item epic-task file-add --epic N --task-num N --file-path PATH [--action ACTION]",
    ),
    AdapterEntry(
        "workflow_item.epic_task.history_insert",
        "yoke workflow-item epic-task history-insert --epic N --task-num N --from-status S --to-status S",
    ),
    AdapterEntry(
        "workflow_item.epic_task.review_seed",
        "yoke workflow-item epic-task review-seed --epic N --task-num N",
    ),
    AdapterEntry(
        "workflow_item.epic_task.review_insert",
        "yoke workflow-item epic-task review-insert --epic N --task-num N --verdict pass|fail --body-file PATH",
    ),
    _read_entry(
        function_id="workflow_item.epic_task.review_get",
        cli_invocation="yoke workflow-item epic-task review-get --epic N --task-num N",
    ),
    _read_entry(
        function_id="workflow_item.epic_task.review_list",
        cli_invocation="yoke workflow-item epic-task review-list --epic N --task-num N [--limit N]",
    ),
    AdapterEntry(
        "workflow_item.epic_task.simulation_upsert",
        "yoke workflow-item epic-task simulation-upsert --epic N --phase P --body-file PATH",
    ),
    _read_entry(
        function_id="workflow_item.epic_task.simulation_get",
        cli_invocation="yoke workflow-item epic-task simulation-get --epic N --phase P",
    ),
    _read_entry(
        function_id="workflow_item.epic_task.submission_receipt_get",
        cli_invocation="yoke workflow-item epic-task submission-receipt-get --epic N --task-num N [--after-note-count N]",
    ),
    AdapterEntry(
        "workflow_item.epic_progress_note.append",
        "yoke workflow-item epic-progress-note append --epic N --task-num N --note-num N --body-file PATH",
    ),
    _read_entry(
        function_id="workflow_item.epic_progress_note.list",
        cli_invocation="yoke workflow-item epic-progress-note list --epic N --task-num N [--limit N]",
    ),
    _read_entry(
        function_id="epic_tasks.list.run",
        cli_invocation="yoke epic-tasks list --epic N",
    ),
    _read_entry(
        function_id="workflow_item.epic_dispatch_chain.get",
        cli_invocation="yoke workflow-item epic-dispatch-chain get --epic N --worktree NAME",
    ),
    _read_entry(
        function_id="workflow_item.epic_dispatch_chain.list",
        cli_invocation="yoke workflow-item epic-dispatch-chain list --epic N",
    ),
    AdapterEntry(
        "workflow_item.epic_dispatch_chain.update",
        "yoke workflow-item epic-dispatch-chain update --epic N --worktree NAME --field FIELD --value TEXT",
    ),
    AdapterEntry(
        "workflow_item.epic_dispatch_chain.refresh_activation",
        "yoke workflow-item epic-dispatch-chain refresh-activation --epic N --worktree NAME --task-num N",
    ),
    AdapterEntry(
        "conduct.epic.proceed_triage_handoff",
        "yoke conduct epic proceed-triage-handoff --epic N [--filed-tickets T1,T2]",
    ),
]


__all__ = ["EPIC_ADAPTERS"]
