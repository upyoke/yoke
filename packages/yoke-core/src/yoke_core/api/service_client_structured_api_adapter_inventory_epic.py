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
        (
            "yoke workflow-item epic-task body-replace --epic PREFIX-N --task-num N (--body TEXT | --body-file PATH | --stdin) [--session-id S] [--json]"
        ),
        notes="Epic task body replace.",
    ),
    AdapterEntry(
        "workflow_item.epic_task.metadata_update",
        (
            "yoke workflow-item epic-task metadata-update --epic PREFIX-N --task-num N --fields-json JSON [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        "workflow_item.epic_task.add",
        (
            "yoke workflow-item epic-task add --epic PREFIX-N --title TEXT [--body TEXT | --body-file PATH] [--worktree NAME] [--context-estimate TEXT] [--dependencies TEXT] [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        "workflow_item.epic_task.remove",
        (
            "yoke workflow-item epic-task remove --epic PREFIX-N --task-num N [--reason TEXT] [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        "workflow_item.epic_task.reassign",
        (
            "yoke workflow-item epic-task reassign --epic PREFIX-N --task-num N --new-worktree NAME [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        "workflow_item.epic_task.split",
        (
            "yoke workflow-item epic-task split --epic PREFIX-N --task-num N --children-json JSON [--session-id S] [--json]"
        ),
    ),
    _read_entry(
        function_id="workflow_item.epic_task.get",
        cli_invocation=(
            "yoke workflow-item epic-task get --epic PREFIX-N --task-num N [--session-id S] [--json]"
        ),
    ),
    _read_entry(
        function_id="workflow_item.epic_task.body_get",
        cli_invocation=(
            "yoke workflow-item epic-task body-get --epic PREFIX-N --task-num N [--output-file PATH] [--full] [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        "workflow_item.epic_task.update_status",
        (
            "yoke workflow-item epic-task update-status --epic PREFIX-N --task-num N --status STATUS [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        "conduct.epic_task.update_status",
        (
            "yoke conduct epic-task update-status --epic PREFIX-N --task-num N --status STATUS [--note TEXT | --note-file PATH] [--no-github] [--no-derive] [--claim-bypass SOURCE] [--session-id S] [--json]"
        ),
        notes="Full conduct status pipeline; unlike workflow_item.epic_task.update_status, this route runs update_status side effects.",
    ),
    AdapterEntry(
        "workflow_item.epic_task.scope_finalize",
        "yoke workflow-item epic-task scope-finalize --epic PREFIX-N "
        "[--session-id S] [--json]",
    ),
    AdapterEntry(
        "workflow_item.epic_task.scope_reopen",
        "yoke workflow-item epic-task scope-reopen --epic PREFIX-N "
        "[--session-id S] [--json]",
    ),
    AdapterEntry(
        "workflow_item.epic_task.history_insert",
        (
            "yoke workflow-item epic-task history-insert --epic PREFIX-N --task-num N --from-status S --to-status S [--note TEXT | --note-file PATH] [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        "workflow_item.epic_task.review_seed",
        (
            "yoke workflow-item epic-task review-seed --epic PREFIX-N --task-num N [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        "workflow_item.epic_task.review_insert",
        (
            "yoke workflow-item epic-task review-insert --epic PREFIX-N --task-num N --verdict pass|fail (--body TEXT | --body-file PATH | --stdin) [--head-sha SHA] [--session-id S] [--json]"
        ),
    ),
    _read_entry(
        function_id="workflow_item.epic_task.review_get",
        cli_invocation=(
            "yoke workflow-item epic-task review-get --epic PREFIX-N --task-num N [--session-id S] [--json]"
        ),
    ),
    _read_entry(
        function_id="workflow_item.epic_task.review_list",
        cli_invocation=(
            "yoke workflow-item epic-task review-list --epic PREFIX-N --task-num N [--limit N] [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        "workflow_item.epic_task.simulation_upsert",
        (
            "yoke workflow-item epic-task simulation-upsert --epic PREFIX-N --phase PHASE (--body TEXT | --body-file PATH | --stdin) [--head-sha COMMIT] [--session-id S] [--json]"
        ),
    ),
    _read_entry(
        function_id="workflow_item.epic_task.simulation_get",
        cli_invocation=(
            "yoke workflow-item epic-task simulation-get --epic PREFIX-N --phase P [--session-id S] [--json]"
        ),
    ),
    _read_entry(
        function_id="workflow_item.epic_task.submission_receipt_get",
        cli_invocation=(
            "yoke workflow-item epic-task submission-receipt-get --epic PREFIX-N --task-num N [--after-note-count N] [--full] [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        "workflow_item.epic_progress_note.append",
        (
            "yoke workflow-item epic-progress-note append --epic PREFIX-N --task-num N --note-num N (--body TEXT | --body-file PATH | --stdin) [--commit-hash SHA] [--session-id S] [--json]"
        ),
    ),
    _read_entry(
        function_id="workflow_item.epic_progress_note.list",
        cli_invocation=(
            "yoke workflow-item epic-progress-note list --epic PREFIX-N --task-num N [--limit N] [--full] [--session-id S] [--json]"
        ),
    ),
    _read_entry(
        function_id="epic_tasks.list.run",
        cli_invocation=(
            "yoke epic-tasks list --epic PREFIX-N [--full] [--session-id S] [--json]"
        ),
    ),
    _read_entry(
        function_id="workflow_item.epic_dispatch_chain.get",
        cli_invocation=(
            "yoke workflow-item epic-dispatch-chain get --epic PREFIX-N --worktree NAME [--session-id S] [--json]"
        ),
    ),
    _read_entry(
        function_id="workflow_item.epic_dispatch_chain.list",
        cli_invocation=(
            "yoke workflow-item epic-dispatch-chain list --epic PREFIX-N [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        "workflow_item.epic_dispatch_chain.update",
        (
            "yoke workflow-item epic-dispatch-chain update --epic PREFIX-N --worktree NAME --field FIELD (--value TEXT | --value-file PATH | --stdin) [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        "workflow_item.epic_dispatch_chain.refresh_activation",
        (
            "yoke workflow-item epic-dispatch-chain refresh-activation --epic PREFIX-N --worktree NAME --task-num N [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        "workflow_item.epic_dispatch_chain.advance",
        (
            "yoke workflow-item epic-dispatch-chain advance --epic PREFIX-N --worktree NAME [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        "conduct.epic.proceed_triage_handoff",
        (
            "yoke conduct epic proceed-triage-handoff --epic PREFIX-N [--recommendation R] [--gap-summary S] [--filed-items T1,T2] [--session-id S] [--json]"
        ),
    ),
]


__all__ = ["EPIC_ADAPTERS"]
