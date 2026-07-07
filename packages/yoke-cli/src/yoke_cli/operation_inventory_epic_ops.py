"""Operation inventory rows for epic workflow wrappers."""

from __future__ import annotations

from typing import Tuple

from yoke_cli.operation_inventory_model import _Row, _w


WRAPPED_ROWS: Tuple[_Row, ...] = (
    _w("yoke workflow-item epic-task body-replace",
       "workflow_item.epic_task"),
    _w("yoke workflow-item epic-task split", "workflow_item.epic_task"),
    _w("yoke workflow-item epic-task reassign", "workflow_item.epic_task"),
    _w("yoke workflow-item epic-task add", "workflow_item.epic_task"),
    _w("yoke workflow-item epic-task remove", "workflow_item.epic_task"),
    _w("yoke workflow-item epic-task metadata-update",
       "workflow_item.epic_task"),
    _w("yoke workflow-item epic-task review-seed",
       "workflow_item.epic_task.review"),
    _w("yoke workflow-item epic-task review-insert",
       "workflow_item.epic_task.review"),
    _w("yoke workflow-item epic-task review-get",
       "workflow_item.epic_task.review"),
    _w("yoke workflow-item epic-task review-list",
       "workflow_item.epic_task.review"),
    _w("yoke workflow-item epic-task body-get", "workflow_item.epic_task"),
    _w("yoke workflow-item epic-task update-status",
       "workflow_item.epic_task"),
    _w("yoke workflow-item epic-task simulation-upsert",
       "workflow_item.epic_task"),
    _w("yoke workflow-item epic-task submission-receipt-get",
       "workflow_item.epic_task"),
    _w("yoke workflow-item epic-progress-note append",
       "workflow_item.epic_progress_note"),
    _w("yoke workflow-item epic-progress-note list",
       "workflow_item.epic_progress_note"),
    _w("yoke epic-tasks list", "epic_tasks"),
    _w("yoke workflow-item epic-task get", "workflow_item.epic_task"),
    _w("yoke workflow-item epic-task simulation-get",
       "workflow_item.epic_task"),
    _w("yoke workflow-item epic-task file-add", "workflow_item.epic_task"),
    _w("yoke workflow-item epic-task history-insert",
       "workflow_item.epic_task"),
    _w("yoke workflow-item epic-dispatch-chain get",
       "workflow_item.epic_dispatch_chain"),
    _w("yoke workflow-item epic-dispatch-chain list",
       "workflow_item.epic_dispatch_chain"),
    _w("yoke workflow-item epic-dispatch-chain update",
       "workflow_item.epic_dispatch_chain"),
    _w("yoke workflow-item epic-dispatch-chain refresh-activation",
       "workflow_item.epic_dispatch_chain"),
    _w("yoke conduct epic-task update-status", "conduct.epic_task"),
    _w("yoke conduct epic proceed-triage-handoff", "conduct.epic"),
)


__all__ = ["WRAPPED_ROWS"]
