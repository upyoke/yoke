"""Success telemetry for typed session work-claim acquisition."""

from __future__ import annotations

from typing import Any, Dict, Optional

from . import sessions_analytics as _sa
from .sessions_analytics import EVENT_WORK_CLAIMED
from .work_claim_targets import (
    TARGET_KIND_EPIC_TASK,
    TARGET_KIND_ITEM,
    WorkClaimTarget,
)


def emit_work_claimed(
    session_id: str,
    claim_id: int,
    target: WorkClaimTarget,
    *,
    linked_path_claim_ids: Optional[list[int]] = None,
    reason: Optional[str] = None,
) -> None:
    """Emit one typed ``WorkClaimed`` event after acquisition commits."""
    context: Dict[str, Any] = {
        "claim_id": claim_id,
        "target_kind": target.kind,
        "claim_type": "exclusive",
    }
    if reason:
        context["claim_reason_intent"] = reason
    item_id: Optional[str] = None
    task_num: Optional[int] = None
    if target.kind == TARGET_KIND_ITEM:
        context["item_id"] = str(target.item_id)
        item_id = str(target.item_id)
    elif target.kind == TARGET_KIND_EPIC_TASK:
        context["epic_id"] = target.epic_id
        context["task_num"] = target.task_num
        item_id = str(target.epic_id)
        task_num = target.task_num
    else:
        context["process_key"] = target.process_key
        context["conflict_group"] = target.conflict_group
        context["linked_path_claim_ids"] = list(linked_path_claim_ids or [])
    _sa._emit_session_event(
        EVENT_WORK_CLAIMED,
        session_id=session_id,
        item_id=item_id,
        task_num=task_num,
        context=context,
    )


__all__ = ["emit_work_claimed"]
