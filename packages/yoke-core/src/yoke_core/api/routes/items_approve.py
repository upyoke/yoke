"""Item approval route sub-router.

Owns ``POST /items/{item_id}/approve`` — promotes a deployment gate for an
item via the shared approval mutation layer and emits the corresponding
``DeploymentApprovalGranted`` event.
"""

from __future__ import annotations

from fastapi.responses import JSONResponse
from fastapi.routing import APIRouter

from yoke_core.domain import db_backend
from yoke_core.domain.approval import parse_flow_stages
from yoke_core.domain.mutations import (
    ItemState,
    prepare_approval,
)
from yoke_core.domain.project_identity import resolve_project_slug
from yoke_core.domain.runs import DeploymentRun, find_active_run_for_item

# Module-level import so test patches against ``yoke_core.api.main.*`` take effect.
import yoke_core.api.main as _main

router = APIRouter()


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


@router.post("/items/{item_id}/approve", response_model=_main.ApproveResponse)
def approve_item(item_id: int, req: _main.ApproveRequest) -> _main.ApproveResponse | JSONResponse:
    """Approve a deployment gate for an item."""
    if req.comment is not None and len(req.comment) > 500:
        return _main._error_response(
            422, "VALIDATION_ERROR",
            "Field 'comment' must be at most 500 characters",
        )

    conn = _main.get_db_readwrite()
    try:
        p = _p(conn)
        row = conn.execute(
            f"SELECT * FROM items WHERE id = {p}", (item_id,)
        ).fetchone()
        if row is None:
            return _main._error_response(
                404, "NOT_FOUND",
                f"Item with id {item_id} not found",
            )

        item_dict = dict(row)

        item_state = ItemState(
            id=item_dict["id"],
            title=item_dict["title"],
            item_type=item_dict["type"],
            status=item_dict["status"],
            priority=item_dict["priority"],
            rework_count=item_dict.get("rework_count", 0),
            frozen=bool(item_dict.get("frozen", 0)),
            project=resolve_project_slug(conn, int(item_dict["project_id"])),
            deployment_flow=item_dict.get("deployment_flow"),
            deploy_stage=item_dict.get("deploy_stage"),
            deployed_to=item_dict.get("deployed_to"),
            worktree=item_dict.get("worktree"),
            merged_at=item_dict.get("merged_at"),
        )

        deployment_flow = item_dict.get("deployment_flow")

        flow_stages = []
        if deployment_flow:
            flow_row = conn.execute(
                f"SELECT stages FROM deployment_flows WHERE id = {p}",
                (deployment_flow,),
            ).fetchone()
            if flow_row:
                flow_stages = parse_flow_stages(flow_row["stages"])

        run_rows = conn.execute(
            f"""SELECT dr.*, p.slug AS project FROM deployment_run_items dri
               JOIN deployment_runs dr ON dr.id = dri.run_id
               JOIN projects p ON p.id = dr.project_id
               WHERE dri.item_id = {p}
               ORDER BY dr.created_at DESC""",
            (item_id,),
        ).fetchall()

        active_run = find_active_run_for_item([
            DeploymentRun(
                id=r["id"],
                project=r["project"],
                flow=r["flow"],
                status=r["status"],
                current_stage=r["current_stage"],
                created_at=r["created_at"],
            )
            for r in run_rows
        ])

        member_item_ids = []
        if active_run:
            member_rows = conn.execute(
                f"SELECT item_id FROM deployment_run_items WHERE run_id = {p}",
                (active_run.id,),
            ).fetchall()
            member_item_ids = [m["item_id"] for m in member_rows]

        approval_result = prepare_approval(
            item=item_state,
            flow_stages=flow_stages,
            active_run=active_run,
            member_item_ids=member_item_ids,
        )

        if not approval_result.success:
            return _main._error_response(
                409,
                approval_result.error_code or "INVALID_STATE",
                approval_result.error or "Unknown error",
            )

        next_stage = approval_result.next_stage
        approved_at = approval_result.approved_at
        run_id = approval_result.run_id

        # Collect every item the UPDATE will touch so we can emit one
        # ``ItemStatusChanged`` per genuine status transition after commit.
        # Skipping items already at ``release`` keeps the emit idempotent
        # for re-runs of the same approval.
        if run_id:
            affected_ids = list(approval_result.member_item_ids)
        else:
            affected_ids = [item_id]

        prior_status: dict[int, str] = {}
        for mid in affected_ids:
            row_prior = conn.execute(
                f"SELECT status FROM items WHERE id = {p}", (mid,)
            ).fetchone()
            if row_prior is not None:
                prior_status[mid] = str(row_prior["status"] or "")

        if run_id:
            conn.execute(
                f"UPDATE deployment_runs SET current_stage = {p} WHERE id = {p}",
                (next_stage, run_id),
            )
            for mid in affected_ids:
                conn.execute(
                    f"UPDATE items SET deploy_stage = {p}, status = 'release', "
                    f"updated_at = {p} WHERE id = {p}",
                    (next_stage, approved_at, mid),
                )
        else:
            conn.execute(
                f"UPDATE items SET deploy_stage = {p}, status = 'release', "
                f"updated_at = {p} WHERE id = {p}",
                (next_stage, approved_at, item_id),
            )

        conn.commit()

        # Record the transition (state) + emit ItemStatusChanged (telemetry)
        # for each member whose status actually transitioned. The shared
        # tail routes through the same native emitter
        # ``backlog.execute_update`` uses.
        from yoke_core.domain.item_status_transitions import (
            record_and_emit_item_status_change,
        )
        for mid in affected_ids:
            old_status = prior_status.get(mid, "")
            if old_status and old_status != "release":
                record_and_emit_item_status_change(
                    conn,
                    item_id=mid,
                    from_status=old_status,
                    to_status="release",
                    source="items-approve",
                )

        deploy_stage = item_dict.get("deploy_stage")
        detail_obj = {
            "item_id": str(item_id),
            "run_id": run_id,
            "stage": deploy_stage,
            "next_stage": next_stage,
            "comment": req.comment,
        }
        try:
            from yoke_core.domain.events import emit_event as _native_emit
            _native_emit(
                "DeploymentApprovalGranted",
                event_kind="lifecycle",
                event_type="deployment_run",
                source_type="script",
                outcome="completed",
                item_id=str(item_id),
                context=detail_obj,
            )
        except Exception:
            pass

        return _main.ApproveResponse(
            id=item_id,
            approved_at=approved_at,
            comment=req.comment,
        )
    except db_backend.operational_error_types(conn) as exc:
        if "database is locked" in str(exc).lower():
            return _main._error_response(
                503, "DB_BUSY",
                "Database is locked. Retry after a short delay.",
            )
        raise
    finally:
        conn.close()


__all__ = ["router"]
