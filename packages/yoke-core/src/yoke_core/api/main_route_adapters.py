"""Route adapters shared by the FastAPI modules.

Owns the small adapter functions route handlers reach for via
``import yoke_core.api.main as _main``: the row-to-response converter,
the standard error JSON envelope, and the SchedulerResult to FrontierState
projection consumed by the decision-engine layer. Project scope is
resolved by ``yoke_core.domain.session_project_scope`` upstream of the
route layer.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi.responses import JSONResponse

from yoke_core.domain.scheduler_types import is_assignable_claim_state
from yoke_core.domain.session import FrontierState
from yoke_core.api.main_models import ErrorDetail, ErrorResponse, ItemObject


def _row_to_item(row: Any, include_body: bool = False) -> ItemObject:
    """Convert a DB row to an ItemObject."""
    d = dict(row)
    d["frozen"] = bool(d.get("frozen", 0))
    d.pop("epic", None)
    if not include_body:
        d.pop("body", None)
    return ItemObject(**d)


def _error_response(status_code: int, code: str, message: str) -> JSONResponse:
    """Build a JSONResponse with the nested ErrorResponse envelope."""
    return JSONResponse(
        status_code=status_code,
        content=ErrorResponse(
            error=ErrorDetail(code=code, message=message)
        ).model_dump(),
    )


def _build_frontier_state(
    schedule,
    drift_review_dict: Optional[Dict[str, Any]] = None,
    last_completed_step: Optional[Dict[str, Any]] = None,
) -> FrontierState:
    """Build a FrontierState from a SchedulerResult for the decision engine."""
    selected_item = schedule.selected_step.item_id if schedule.selected_step else None
    scheduler_ctx: Dict[str, Any] = {}
    if schedule.selected_step:
        ss = schedule.selected_step
        scheduler_ctx = {
            "next_step": ss.next_step.value if hasattr(ss.next_step, "value") else str(ss.next_step),
            "item_type": ss.item_type,
            "status": ss.status,
            "title": ss.title,
            "rank": ss.rank,
            "explanation": ss.explanation,
            "adapter": ss.adapter,
        }
    blocked_details_list: List[Dict[str, Any]] = []
    for bs in schedule.blocked_steps:
        for ge in bs.gate_evaluations:
            if not ge.satisfied:
                blocked_details_list.append({
                    "item_id": bs.item_id,
                    "blocking_item": ge.blocking_item,
                    "gate_point": ge.gate_point,
                    "satisfaction": ge.satisfaction,
                    "rationale": getattr(ge, "rationale", ""),
                    "reason": ge.reason,
                })
    lane_filtered_items = getattr(schedule, "lane_filtered_items", None)
    return FrontierState(
        runnable_items=[
            s.item_id
            for s in schedule.ranked_steps
            if is_assignable_claim_state(s.claim_state)
        ],
        blocked_items=[s.item_id for s in schedule.blocked_steps],
        exceptional_items=[s.item_id for s in schedule.exceptional_steps],
        blocked_details=blocked_details_list if blocked_details_list else None,
        sml_coherent=schedule.sml_state.coherent,
        drift_review=drift_review_dict,
        selected_item=selected_item,
        scheduler_context=scheduler_ctx,
        lane_filtered_count=getattr(schedule, "lane_filtered_count", 0),
        lane_filtered_items=list(lane_filtered_items) if lane_filtered_items else None,
        last_completed_step=last_completed_step,
    )

