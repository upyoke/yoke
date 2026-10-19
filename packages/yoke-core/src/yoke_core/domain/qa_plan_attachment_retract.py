"""Retract a mis-specified item plan attachment and what it materialized."""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain.db_helpers import (
    instant_parameter,
    utc_now,
    query_one,
    query_rows,
)
from yoke_core.domain.qa_plan_management import QaPlanError
from yoke_core.domain.schema_common import _column_exists


def retract_requirements(
    conn: Any,
    requirement_ids: list[int],
    *,
    reason: str,
    source: str,
) -> None:
    """Retire the selected requirements in the caller's transaction, keeping rows."""
    if not requirement_ids:
        return
    now = instant_parameter(conn, utc_now())
    conn.execute(
        "UPDATE qa_requirements SET retracted_at=%s, "
        "retraction_rationale=%s, retraction_source=%s, "
        "waived_at=NULL, waiver_rationale=NULL, waiver_source=NULL, "
        "superseded_by_requirement_id=NULL, superseded_at=NULL, "
        "supersession_rationale=NULL, supersession_source=NULL "
        "WHERE id=ANY(%s)",
        (now, reason, source, [int(req_id) for req_id in requirement_ids]),
    )


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
    waived, not superseded — and any recorded run or verdict refuses, because that
    would rewrite execution evidence. Repeating a withdrawal also
    retires copies an older serving build admitted after the first call.
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
    already_retracted = bool(attachment.get("retracted_at"))
    requirements = query_rows(
        conn,
        "SELECT r.id, r.retracted_at, EXISTS(SELECT 1 FROM qa_runs run "
        "WHERE run.qa_requirement_id=r.id) AS has_recorded_run "
        "FROM qa_requirements r WHERE plan_id=%s AND qa_phase=%s AND ("
        "(item_id=%s AND (workflow_transition_id=%s "
        "OR workflow_transition_id IS NULL)) "
        "OR deployment_member_item_id=%s)",
        (
            int(plan_id),
            str(attachment["qa_phase"]),
            int(item_id),
            str(transition_id),
            int(item_id),
        ),
    )
    from yoke_core.domain.deployment_qa_shared_copy_reads import shared_plan_copies

    shared = shared_plan_copies(
        conn, int(item_id), int(plan_id), include_withdrawn=True
    )
    for row in shared:
        row["has_recorded_run"] = (
            conn.execute(
                "SELECT 1 FROM qa_runs WHERE qa_requirement_id=%s LIMIT 1",
                (row["id"],),
            ).fetchone()
            is not None
        )
    requirements.extend(shared)
    for row in requirements:
        if row["has_recorded_run"]:
            raise QaPlanError(
                f"attachment_has_recorded_run: requirement {int(row['id'])} "
                "already has a recorded run or verdict; preserve its evidence "
                "and use yoke qa requirement waive or supersede --help for "
                "settlement instead of retracting the attachment"
            )
    requirements = [row for row in requirements if not row["retracted_at"]]
    if not already_retracted:
        now = instant_parameter(conn, utc_now())
        conn.execute(
            "UPDATE qa_plan_item_attachments SET retracted_at=%s, "
            "retraction_rationale=%s, retraction_source=%s, "
            "retracted_by_actor_id=%s WHERE item_id=%s AND transition_id=%s "
            "AND plan_id=%s",
            (
                now,
                reason,
                source,
                actor_id,
                int(item_id),
                str(transition_id),
                int(plan_id),
            ),
        )
    from yoke_core.domain.deployment_qa_shared_plans import member_group_digests

    retired = []
    for row in requirements:
        if row.get("deployment_member_item_id") is None and row.get(
            "deployment_run_id"
        ):
            members = query_rows(
                conn,
                "SELECT item_id FROM deployment_run_items WHERE run_id=%s AND item_id<>%s",
                (row["deployment_run_id"], item_id),
            )
            if any(
                row["execution_target_digest"]
                in member_group_digests(
                    conn,
                    row["deployment_run_id"],
                    row["deployment_stage"],
                    int(member["item_id"]),
                )
                for member in members
            ):
                continue
        retired.append(int(row["id"]))
    retract_requirements(conn, retired, reason=reason, source=source)
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
            qa_phase=str(attachment["qa_phase"]),
            rationale=reason,
            source=source,
        )
    if commit and retired:
        from yoke_core.domain.deployment_member_close_out_retry import (
            after_record_settled,
        )

        after_record_settled(conn, item_id=int(item_id))
    return {
        "retracted": True,
        "already_retracted": already_retracted,
        "item_id": int(item_id),
        "plan_id": int(plan_id),
        "transition_id": str(transition_id),
        "reason": reason,
        "retired_requirement_ids": retired,
    }


__all__ = ["retract_plan_from_item", "retract_requirements"]
