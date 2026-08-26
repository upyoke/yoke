"""Success telemetry for typed session work-claim acquisition."""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from . import sessions_analytics as _sa
from .sessions_analytics import EVENT_WORK_CLAIMED, EVENT_WORK_RECLAIMED
from .work_claim_targets import (
    TARGET_KIND_EPIC_TASK,
    TARGET_KIND_ITEM,
    TARGET_KIND_STEERING_SCOPE,
    WorkClaimTarget,
    from_row,
)

EVENT_STEERING_SCOPE_CLAIMED = "SteeringScopeClaimed"
EVENT_STEERING_SCOPE_RELEASED = "SteeringScopeReleased"


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


def _steering_context(
    claim_id: int,
    target: WorkClaimTarget,
) -> Dict[str, Any]:
    if target.kind != TARGET_KIND_STEERING_SCOPE:
        raise ValueError("steering claim telemetry requires a steering_scope target")
    return {
        "claim_id": int(claim_id),
        "target_kind": target.kind,
        "claim_type": "exclusive",
        "steering_project_id": int(target.steering_project_id),
        "steering_strategy_doc_slugs": list(target.steering_strategy_doc_slugs or ()),
    }


def emit_steering_scope_claimed(
    session_id: str,
    claim_id: int,
    target: WorkClaimTarget,
    *,
    reason: Optional[str] = None,
) -> None:
    """Emit the steering-specific acquisition event after commit."""
    context = _steering_context(claim_id, target)
    context["holder_session_id"] = session_id
    if reason:
        context["claim_reason_intent"] = reason
    _sa._emit_session_event(
        EVENT_STEERING_SCOPE_CLAIMED,
        session_id=session_id,
        context=context,
    )


def emit_steering_scope_released(
    session_id: str,
    claim_id: int,
    target: WorkClaimTarget,
    *,
    reason: str,
    reclaimed: bool = False,
) -> None:
    """Emit ordinary and stale-sweep steering release evidence."""
    context = _steering_context(claim_id, target)
    context.update(
        {
            "holder_session_id": session_id,
            "release_reason_intent": reason,
            "release_mode": "reclaimed" if reclaimed else "normal",
        }
    )
    _sa._emit_session_event(
        EVENT_STEERING_SCOPE_RELEASED,
        session_id=session_id,
        context=context,
    )


def emit_reclaimed_work_claim(
    session_id: str,
    claim_row: Mapping[str, Any],
) -> None:
    """Emit target-specific stale-reclaim evidence for one released claim."""
    if claim_row["target_kind"] == TARGET_KIND_STEERING_SCOPE:
        emit_steering_scope_released(
            session_id,
            int(claim_row["id"]),
            from_row(claim_row),
            reason="stale_session_reclaimed",
            reclaimed=True,
        )
        return
    _sa._emit_session_event(
        EVENT_WORK_RECLAIMED,
        session_id=session_id,
        item_id=(
            str(claim_row["item_id"])
            if claim_row["item_id"] is not None
            else None
        ),
        task_num=claim_row["task_num"],
        context={
            "claim_id": claim_row["id"],
            "reason": "stale_session_reclaimed",
        },
    )


__all__ = [
    "EVENT_STEERING_SCOPE_CLAIMED",
    "EVENT_STEERING_SCOPE_RELEASED",
    "emit_reclaimed_work_claim",
    "emit_steering_scope_claimed",
    "emit_steering_scope_released",
    "emit_work_claimed",
]
