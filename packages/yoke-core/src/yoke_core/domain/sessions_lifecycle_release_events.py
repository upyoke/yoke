"""Post-commit success telemetry for execution-owned claim release."""

from __future__ import annotations

from typing import Any, Dict, Optional

from . import sessions_analytics as _sa
from .sessions_analytics import EVENT_WORK_RELEASED
from .work_claim_targets import (
    TARGET_KIND_EPIC_TASK,
    TARGET_KIND_ITEM,
    WorkClaimTarget,
)

POST_COMMIT_RECEIPT_KEY = "_post_commit_receipt"


def build_work_release_post_commit_receipt(
    *,
    session_id: str,
    target: WorkClaimTarget,
    claim_id: int,
    canonical_reason: str,
    reason: str,
    released_at: str,
) -> Dict[str, Any]:
    """Build the event receipt retained until the transaction commits."""
    item_id: Optional[str] = None
    task_num: Optional[int] = None
    context: Dict[str, Any] = {
        "claim_id": claim_id,
        "release_reason": canonical_reason,
        "release_reason_intent": reason,
        "execution_owned": True,
        "target_kind": target.kind,
    }
    if target.kind == TARGET_KIND_ITEM:
        item_id = str(target.item_id)
    elif target.kind == TARGET_KIND_EPIC_TASK:
        item_id = str(target.epic_id)
        task_num = target.task_num
    else:
        context["process_key"] = target.process_key
        context["conflict_group"] = target.conflict_group

    idea_release: Optional[Dict[str, Any]] = None
    if target.kind == TARGET_KIND_ITEM and target.item_id is not None:
        idea_release = {
            "session_id": session_id,
            "target_item_id": int(target.item_id),
            "claim_id": int(claim_id),
            "release_reason_intent": reason,
            "released_at": released_at,
        }
    return {
        "session_id": session_id,
        "item_id": item_id,
        "task_num": task_num,
        "context": context,
        "idea_release": idea_release,
    }


def emit_work_release_post_commit(
    conn: Any,
    receipt: Dict[str, Any],
) -> None:
    """Emit success telemetry after the caller's release transaction commits."""
    _sa._emit_session_event(
        EVENT_WORK_RELEASED,
        session_id=receipt["session_id"],
        item_id=receipt["item_id"],
        task_num=receipt["task_num"],
        context=receipt["context"],
    )

    idea_release = receipt.get("idea_release")
    if idea_release is not None:
        from .idea_claim_events import emit_if_idea_release

        emit_if_idea_release(conn, **idea_release)


__all__ = [
    "POST_COMMIT_RECEIPT_KEY",
    "build_work_release_post_commit_receipt",
    "emit_work_release_post_commit",
]
