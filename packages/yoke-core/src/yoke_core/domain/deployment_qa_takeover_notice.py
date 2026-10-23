"""Tell each moved member owner that item QA now waits on the successor."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from yoke_core.domain.db_savepoint import SavepointLostError, savepoint
from yoke_core.domain.deployment_run_driver_notice import push_member_notice
from yoke_core.domain.project_identity import render_item_ref

_SEND_SAVEPOINT = "_yoke_moved_member_qa_notice"


def item_qa_stage_name(stages: Sequence[Mapping[str, Any]]) -> str:
    """The flow's item-scoped QA stage, or ``item-qa`` when it has not named one."""
    for stage in stages:
        if stage.get("step_runner") == "qa" and stage.get("scope") == "item":
            name = str(stage.get("name") or "").strip()
            if name:
                return name
    return "item-qa"


def moved_member_body(*, item_ref: str, old_id: str, new_id: str, stage_name: str) -> str:
    """One notice: QA moved, and the predecessor wake is no longer the command."""
    return (
        f"{item_ref}'s QA moved from run {old_id} to run {new_id}. "
        f"It opens when {new_id} reaches item QA stage {stage_name!r}. "
        "The successor's QA dispatch will wake you; do not act on the "
        "predecessor's wake."
    )


def notify_moved_member_qa(
    conn: Any,
    *,
    old_id: str,
    new_id: str,
    item_ids: Sequence[int],
    stages: Sequence[Mapping[str, Any]],
) -> None:
    """Reach each moved member once. A send failure refuses the takeover."""
    stage_name = item_qa_stage_name(stages)
    for item_id in item_ids:
        item = conn.execute(
            "SELECT project_id FROM items WHERE id=%s", (int(item_id),)
        ).fetchone()
        if item is None:
            raise ValueError(
                f"moved_member_qa_notice_failed: item {item_id} disappeared "
                f"during takeover onto {new_id}; retry the creation"
            )
        project_id = int(item["project_id"] if hasattr(item, "keys") else item[0])
        item_ref = render_item_ref(conn, int(item_id))
        body = moved_member_body(
            item_ref=item_ref, old_id=old_id, new_id=new_id, stage_name=stage_name
        )
        key = f"deployment-qa-moved:{new_id}:{int(item_id)}"
        try:
            with savepoint(conn, _SEND_SAVEPOINT, owns=False):
                push_member_notice(
                    conn,
                    item_id=int(item_id),
                    project_id=project_id,
                    body_for_route=lambda route, body=body: body,
                    idempotency_key=key,
                )
        except SavepointLostError:
            raise
        except Exception as exc:
            raise ValueError(
                f"moved_member_qa_notice_failed: could not tell {item_ref} that "
                f"QA moved to run {new_id}; retry the creation. Cause: {exc}"
            ) from exc


__all__ = ["item_qa_stage_name", "moved_member_body", "notify_moved_member_qa"]
