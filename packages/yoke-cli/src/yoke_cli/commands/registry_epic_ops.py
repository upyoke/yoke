"""Epic workflow subcommand registry slice."""

from __future__ import annotations

from typing import Callable, Dict, List, Tuple

from yoke_cli.commands import flag_adapters as _adapters
from yoke_cli.commands.adapters import epic_ops as _ops

AdapterFn = Callable[[List[str]], int]

EPIC_OPS_SUBCOMMAND_REGISTRY: Dict[Tuple[str, ...], Tuple[str, AdapterFn]] = {
    ("workflow-item", "epic-task", "body-replace"):
        ("workflow_item.epic_task.body_replace", _adapters.epic_task_body_replace),
    ("workflow-item", "epic-task", "split"):
        ("workflow_item.epic_task.split", _adapters.epic_task_split),
    ("workflow-item", "epic-task", "reassign"):
        ("workflow_item.epic_task.reassign", _adapters.epic_task_reassign),
    ("workflow-item", "epic-task", "add"):
        ("workflow_item.epic_task.add", _adapters.epic_task_add),
    ("workflow-item", "epic-task", "remove"):
        ("workflow_item.epic_task.remove", _adapters.epic_task_remove),
    ("workflow-item", "epic-task", "metadata-update"):
        ("workflow_item.epic_task.metadata_update",
         _adapters.epic_task_metadata_update),
    ("workflow-item", "epic-task", "review-seed"):
        ("workflow_item.epic_task.review_seed",
         _adapters.epic_task_review_seed),
    ("workflow-item", "epic-task", "review-insert"):
        ("workflow_item.epic_task.review_insert",
         _adapters.epic_task_review_insert),
    ("workflow-item", "epic-task", "review-get"):
        ("workflow_item.epic_task.review_get", _adapters.epic_task_review_get),
    ("workflow-item", "epic-task", "review-list"):
        ("workflow_item.epic_task.review_list",
         _adapters.epic_task_review_list),
    ("workflow-item", "epic-task", "body-get"):
        ("workflow_item.epic_task.body_get", _adapters.epic_task_body_get),
    ("workflow-item", "epic-task", "update-status"):
        ("workflow_item.epic_task.update_status",
         _adapters.epic_task_update_status),
    ("workflow-item", "epic-task", "simulation-upsert"):
        ("workflow_item.epic_task.simulation_upsert",
         _adapters.epic_task_simulation_upsert),
    ("workflow-item", "epic-task", "submission-receipt-get"):
        ("workflow_item.epic_task.submission_receipt_get",
         _adapters.epic_task_submission_receipt_get),
    ("workflow-item", "epic-progress-note", "append"):
        ("workflow_item.epic_progress_note.append",
         _adapters.epic_progress_note_append),
    ("workflow-item", "epic-progress-note", "list"):
        ("workflow_item.epic_progress_note.list",
         _adapters.epic_progress_note_list),
    ("epic-tasks", "list"): ("epic_tasks.list.run", _adapters.epic_tasks_list),
    ("workflow-item", "epic-task", "get"):
        ("workflow_item.epic_task.get", _ops.epic_task_get),
    ("workflow-item", "epic-task", "simulation-get"):
        ("workflow_item.epic_task.simulation_get", _ops.epic_task_simulation_get),
    ("workflow-item", "epic-task", "file-add"):
        ("workflow_item.epic_task.file_add", _ops.epic_task_file_add),
    ("workflow-item", "epic-task", "history-insert"):
        ("workflow_item.epic_task.history_insert",
         _ops.epic_task_history_insert),
    ("workflow-item", "epic-dispatch-chain", "get"):
        ("workflow_item.epic_dispatch_chain.get",
         _ops.epic_dispatch_chain_get),
    ("workflow-item", "epic-dispatch-chain", "list"):
        ("workflow_item.epic_dispatch_chain.list",
         _ops.epic_dispatch_chain_list),
    ("workflow-item", "epic-dispatch-chain", "update"):
        ("workflow_item.epic_dispatch_chain.update",
         _ops.epic_dispatch_chain_update),
    ("workflow-item", "epic-dispatch-chain", "refresh-activation"):
        ("workflow_item.epic_dispatch_chain.refresh_activation",
         _ops.epic_dispatch_chain_refresh_activation),
    ("conduct", "epic-task", "update-status"):
        ("conduct.epic_task.update_status",
         _ops.conduct_epic_task_update_status),
    ("conduct", "epic", "proceed-triage-handoff"):
        ("conduct.epic.proceed_triage_handoff",
         _ops.conduct_epic_proceed_triage_handoff),
}


__all__ = ["EPIC_OPS_SUBCOMMAND_REGISTRY"]
