"""Resolve a deployment run stage through the shared Inbox authority.

The deployment runner consumes the resolved decision and remains the only
surface that advances run and member-item deployment state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from yoke_core.domain.approval import parse_flow_stages, resolve_approval
from yoke_core.domain.db_helpers import connect, iso8601_now, query_one, query_rows


@dataclass(frozen=True)
class RunApproval:
    run_id: str
    project: str
    approved_stage: str
    next_stage: str
    approved_at: str
    member_item_ids: tuple[int, ...]
    decision_request_id: Optional[int] = None


class RunApprovalRejected(ValueError):
    """The requested run cannot be approved in its current state."""


def approve_run(
    run_id: str,
    *,
    actor_id: int,
    session_id: str = "",
    note: Optional[str] = None,
) -> RunApproval:
    """Resolve the run stage's Inbox decision without moving run state."""
    from yoke_core.domain.decision_request_resolution import (
        resolve_decision_request,
    )
    from yoke_core.domain.deployment_approval_requests import (
        evaluate_deployment_stage_approval,
    )

    conn = connect()
    try:
        run = query_one(
            conn,
            "SELECT dr.id, p.slug AS project, dr.flow, dr.status, "
            "dr.current_stage, df.stages "
            "FROM deployment_runs dr "
            "JOIN projects p ON p.id = dr.project_id "
            "JOIN deployment_flows df ON df.id = dr.flow "
            "WHERE dr.id=%s FOR UPDATE",
            (run_id,),
        )
        if run is None:
            raise LookupError(f"deployment run '{run_id}' not found")
        if run["status"] != "executing":
            raise RunApprovalRejected(
                f"deployment run '{run_id}' has status '{run['status']}'; "
                "only executing runs can be approved"
            )
        approved_stage = str(run["current_stage"] or "")
        if not approved_stage:
            raise RunApprovalRejected(f"deployment run '{run_id}' has no current stage")
        try:
            stages = parse_flow_stages(str(run["stages"]))
        except (TypeError, ValueError) as exc:
            raise RunApprovalRejected(
                f"deployment flow '{run['flow']}' has invalid stages: {exc}"
            ) from exc
        resolution = resolve_approval(stages, approved_stage)
        if not resolution.approved or not resolution.next_stage:
            raise RunApprovalRejected(resolution.error or "approval rejected")

        next_stage = resolution.next_stage
        approved_at = iso8601_now()
        rows = query_rows(
            conn,
            "SELECT item_id FROM deployment_run_items WHERE run_id=%s ORDER BY item_id",
            (run_id,),
        )
        member_item_ids = tuple(int(row["item_id"]) for row in rows)
        verdict = evaluate_deployment_stage_approval(
            conn,
            run_id=run_id,
            session_id=session_id,
        )
        if verdict.request_status != "pending":
            raise RunApprovalRejected(
                f"deployment run '{run_id}' stage "
                f"{approved_stage!r} is {verdict.reason} "
                f"(decision request {verdict.request_id})"
            )
        resolve_decision_request(
            conn,
            int(verdict.request_id),
            actor_id=actor_id,
            action="approve",
            note=note,
            session_id=session_id,
            resolved_at=approved_at,
        )
        return RunApproval(
            run_id=run_id,
            project=str(run["project"]),
            approved_stage=approved_stage,
            next_stage=next_stage,
            approved_at=approved_at,
            member_item_ids=member_item_ids,
            decision_request_id=int(verdict.request_id),
        )
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def emit_run_approval(
    approval: RunApproval,
    *,
    actor_id: Optional[str],
    session_id: Optional[str],
    note: Optional[str],
) -> Optional[str]:
    """Write the Yoke audit event after the authoritative mutation."""
    from yoke_core.domain.events import emit_event

    result = emit_event(
        "DeploymentApprovalGranted",
        event_kind="lifecycle",
        event_type="deployment_run",
        source_type="agent",
        session_id=session_id or "",
        project=approval.project,
        agent=actor_id or "operator",
        context={
            "run_id": approval.run_id,
            "approved_stage": approval.approved_stage,
            "next_stage": approval.next_stage,
            "approved_at": approval.approved_at,
            "approver_actor_id": actor_id,
            "approver_session_id": session_id,
            "note": note,
            "member_item_ids": list(approval.member_item_ids),
        },
    )
    return result.event_id if result.ok else None


__all__ = [
    "RunApproval",
    "RunApprovalRejected",
    "approve_run",
    "emit_run_approval",
]
