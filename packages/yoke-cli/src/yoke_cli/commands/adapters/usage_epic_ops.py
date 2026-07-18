"""Usage lines for epic workflow adapters."""

from __future__ import annotations

from typing import Dict

from yoke_cli.commands.adapters.epic_progress import (
    EPIC_PROGRESS_NOTE_APPEND_USAGE,
    EPIC_PROGRESS_NOTE_LIST_USAGE,
    EPIC_TASKS_LIST_USAGE,
)
from yoke_cli.commands.adapters.epic_task import (
    EPIC_TASK_ADD_USAGE,
    EPIC_TASK_BODY_REPLACE_USAGE,
    EPIC_TASK_METADATA_UPDATE_USAGE,
    EPIC_TASK_REASSIGN_USAGE,
    EPIC_TASK_REMOVE_USAGE,
    EPIC_TASK_SPLIT_USAGE,
)
from yoke_cli.commands.adapters import epic_ops as _ops
from yoke_cli.commands.adapters import epic_review as _review
from yoke_cli.commands.adapters import epic_state as _state


EPIC_USAGE: Dict[str, str] = {
    "workflow_item.epic_task.body_replace": EPIC_TASK_BODY_REPLACE_USAGE,
    "workflow_item.epic_task.split": EPIC_TASK_SPLIT_USAGE,
    "workflow_item.epic_task.reassign": EPIC_TASK_REASSIGN_USAGE,
    "workflow_item.epic_task.add": EPIC_TASK_ADD_USAGE,
    "workflow_item.epic_task.remove": EPIC_TASK_REMOVE_USAGE,
    "workflow_item.epic_task.metadata_update": EPIC_TASK_METADATA_UPDATE_USAGE,
    "workflow_item.epic_task.review_seed": _review.EPIC_TASK_REVIEW_SEED_USAGE,
    "workflow_item.epic_task.review_insert":
        _review.EPIC_TASK_REVIEW_INSERT_USAGE,
    "workflow_item.epic_task.review_get": _review.EPIC_TASK_REVIEW_GET_USAGE,
    "workflow_item.epic_task.review_list": _review.EPIC_TASK_REVIEW_LIST_USAGE,
    "workflow_item.epic_task.body_get": _state.EPIC_TASK_BODY_GET_USAGE,
    "workflow_item.epic_task.update_status":
        _state.EPIC_TASK_UPDATE_STATUS_USAGE,
    "workflow_item.epic_task.simulation_upsert":
        _state.EPIC_TASK_SIMULATION_UPSERT_USAGE,
    "workflow_item.epic_task.submission_receipt_get":
        _state.EPIC_TASK_SUBMISSION_RECEIPT_GET_USAGE,
    "workflow_item.epic_progress_note.append":
        EPIC_PROGRESS_NOTE_APPEND_USAGE,
    "workflow_item.epic_progress_note.list": EPIC_PROGRESS_NOTE_LIST_USAGE,
    "epic_tasks.list.run": EPIC_TASKS_LIST_USAGE,
    "workflow_item.epic_task.get": _ops.EPIC_TASK_GET_USAGE,
    "workflow_item.epic_task.simulation_get":
        _ops.EPIC_TASK_SIMULATION_GET_USAGE,
    "workflow_item.epic_task.file_add": _ops.EPIC_TASK_FILE_ADD_USAGE,
    "workflow_item.epic_task.history_insert":
        _ops.EPIC_TASK_HISTORY_INSERT_USAGE,
    "workflow_item.epic_dispatch_chain.get":
        _ops.EPIC_DISPATCH_CHAIN_GET_USAGE,
    "workflow_item.epic_dispatch_chain.list":
        _ops.EPIC_DISPATCH_CHAIN_LIST_USAGE,
    "workflow_item.epic_dispatch_chain.update":
        _ops.EPIC_DISPATCH_CHAIN_UPDATE_USAGE,
    "workflow_item.epic_dispatch_chain.refresh_activation":
        _ops.EPIC_DISPATCH_CHAIN_REFRESH_ACTIVATION_USAGE,
    "workflow_item.epic_dispatch_chain.advance":
        _ops.EPIC_DISPATCH_CHAIN_ADVANCE_USAGE,
    "conduct.epic_task.update_status":
        _ops.CONDUCT_EPIC_TASK_UPDATE_STATUS_USAGE,
    "conduct.epic.proceed_triage_handoff":
        _ops.CONDUCT_EPIC_PROCEED_TRIAGE_HANDOFF_USAGE,
}


__all__ = ["EPIC_USAGE"]
