"""Retract a mis-specified item plan attachment and what it materialized."""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain.db_helpers import iso8601_now, query_one, query_rows
from yoke_core.domain.qa_plan_management import QaPlanError
from yoke_core.domain.schema_common import _column_exists


def retract_plan_from_item(
    conn: Any,
    *,
    item_id: int,
    plan_id: int,
    transition_id: str,
    reason: str,
    actor_id: Optional[int] = None,
    source: str = "agent",
    commit: bool = True,
) -> dict[str, Any]:
    """Withdraw a standing attachment so it stops answering future runs.

    The row stays. Requirements it materialized retire as retracted — not
    waived, not superseded — and a passing verdict refuses, because that
    would rewrite settled delivery evidence.
    """
    reason = str(reason or "").strip()
    if not reason:
        raise QaPlanError(
            "retraction requires a reason why the attachment was mis-scoped"
        )
    if source not in {"agent", "operator"}:
        raise QaPlanError("source must be one of ['agent', 'operator']")
    if not _column_exists(conn, "qa_plan_item_attachments", "retracted_at"):
        raise QaPlanError(
            "this control plane has no retraction columns yet; deploy the "
            "build that adds them, then retry"
        )
    attachment = query_one(
        conn,
        "SELECT qa_phase, retracted_at FROM qa_plan_item_attachments "
        "WHERE item_id=%s AND transition_id=%s AND plan_id=%s",
        (int(item_id), str(transition_id), int(plan_id)),
    )
    if attachment is None:
        raise QaPlanError("no such item plan attachment")
    if attachment.get("retracted_at"):
        return {
            "retracted": True,
            "already_retracted": True,
            "item_id": int(item_id),
            "plan_id": int(plan_id),
            "transition_id": str(transition_id),
            "reason": str(reason),
            "retired_requirement_ids": [],
        }
    if str(attachment["qa_phase"] or "") != "post_deploy":
        raise QaPlanError(
            "retraction retires a mis-specified post-deploy attachment, not "
            "a verification case. A failing verification case is an "
            "unwelcome verdict and still owes evidence."
        )
    from yoke_core.domain.qa_requirement_supersession import latest_verdict

    requirements = query_rows(
        conn,
        "SELECT id FROM qa_requirements WHERE plan_id=%s AND ("
        "(item_id=%s AND (workflow_transition_id=%s "
        "OR workflow_transition_id IS NULL)) "
        "OR deployment_member_item_id=%s)",
        (int(plan_id), int(item_id), str(transition_id), int(item_id)),
    )
    for row in requirements:
        if latest_verdict(conn, int(row["id"])) == "pass":
            raise QaPlanError(
                f"requirement {int(row['id'])} already recorded a passing "
                "verdict, so retracting it would rewrite settled delivery "
                "evidence"
            )
    now = iso8601_now()
    conn.execute(
        "UPDATE qa_plan_item_attachments SET retracted_at=%s, "
        "retraction_rationale=%s, retraction_source=%s, "
        "retracted_by_actor_id=%s WHERE item_id=%s AND transition_id=%s "
        "AND plan_id=%s",
        (now, reason, source, actor_id, int(item_id), str(transition_id), int(plan_id)),
    )
    retired: list[int] = []
    for row in requirements:
        req_id = int(row["id"])
        conn.execute(
            "UPDATE qa_requirements SET retracted_at=%s, "
            "retraction_rationale=%s, retraction_source=%s, "
            "waived_at=NULL, waiver_rationale=NULL, waiver_source=NULL, "
            "superseded_by_requirement_id=NULL, superseded_at=NULL, "
            "supersession_rationale=NULL, supersession_source=NULL "
            "WHERE id=%s",
            (now, reason, source, req_id),
        )
        retired.append(req_id)
    if commit:
        conn.commit()
    from yoke_core.domain.qa_events import emit_qa_requirement_event

    for req_id in retired:
        emit_qa_requirement_event(
            conn,
            db_path=None,
            event_name="QARequirementRetracted",
            requirement_id=req_id,
            qa_kind="plan_case",
            qa_phase="post_deploy",
            rationale=reason,
            source=source,
        )
    return {
        "retracted": True,
        "already_retracted": False,
        "item_id": int(item_id),
        "plan_id": int(plan_id),
        "transition_id": str(transition_id),
        "reason": reason,
        "retired_requirement_ids": retired,
    }


__all__ = ["retract_plan_from_item"]
