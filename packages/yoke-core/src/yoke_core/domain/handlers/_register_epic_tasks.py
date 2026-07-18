"""Handler registrations for epic task/conduct workflow handlers.
"""
from __future__ import annotations

from yoke_core.domain.handlers.conduct_epic_pipeline import (
    REGISTRATIONS as _CONDUCT_EPIC_PIPELINE_REGS,
)
from yoke_core.domain.handlers.workflow_item_epic_task import (
    REGISTRATIONS as _EPIC_TASK_REGS,
)
from yoke_core.domain.handlers.workflow_item_epic_task_ops import (
    REGISTRATIONS as _EPIC_TASK_OPS_REGS,
)
from yoke_core.domain.handlers.workflow_item_epic_dispatch_advance import (
    REGISTRATIONS as _EPIC_DISPATCH_ADVANCE_REGS,
)
from yoke_core.domain.handlers.workflow_item_epic_task_review import (
    REGISTRATIONS as _EPIC_TASK_REVIEW_REGS,
)
from yoke_core.domain.handlers.workflow_item_epic_task_state import (
    REGISTRATIONS as _EPIC_TASK_STATE_REGS,
)
from yoke_core.domain.handlers.workflow_item_epic_progress_note import (
    REGISTRATIONS as _EPIC_PROGRESS_NOTE_REGS,
)


def register(registry) -> None:
    """Register the workflow_item.* handler families via the given registry."""
    for _entry in (
        _EPIC_TASK_REGS
        + _EPIC_DISPATCH_ADVANCE_REGS
        + _EPIC_TASK_OPS_REGS
        + _EPIC_TASK_REVIEW_REGS
        + _EPIC_TASK_STATE_REGS
        + _EPIC_PROGRESS_NOTE_REGS
        + _CONDUCT_EPIC_PIPELINE_REGS
    ):
        registry.register(**_entry)
