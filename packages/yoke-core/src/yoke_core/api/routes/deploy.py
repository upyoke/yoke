"""Deployment and frontier route handlers — extracted from main.py.

Covers: charge/frontier, charge/schedule, dependency planning.

DB helpers and shared models are accessed via ``_main`` module reference
so that test patches against ``yoke_core.api.main.*`` take effect.
"""

from __future__ import annotations

from typing import List, Optional, Union

from fastapi import Query
from fastapi.responses import JSONResponse
from fastapi.routing import APIRouter
from pydantic import BaseModel, Field

from yoke_core.domain import db_backend
from yoke_core.domain.frontier import (
    AdapterCategory,
    FrontierItem,
    FrontierResult,
    compute_frontier as compute_domain_frontier,
)
from yoke_core.domain.scheduler import compute_schedule
from yoke_core.domain.dependency_planning import (
    evaluate_item_gate,
    plan_candidate_set,
)
from yoke_core.domain.project_identity import resolve_project_slug

# Module-level import for patchable names.
import yoke_core.api.main as _main


router = APIRouter()


# ---------------------------------------------------------------------------
# Frontier / Charge helpers
# ---------------------------------------------------------------------------


def _frontier_item_to_model(fi: FrontierItem) -> _main.FrontierItemModel:
    """Convert a domain FrontierItem dataclass to its Pydantic model."""
    return _main.FrontierItemModel(
        item_id=fi.item_id,
        title=fi.title,
        status=fi.status,
        priority=fi.priority,
        project=fi.project,
        item_type=fi.item_type,
        adapter=fi.adapter.value if isinstance(fi.adapter, AdapterCategory) else fi.adapter,
        blocked_by=fi.blocked_by,
        blocked_reasons=fi.blocked_reasons,
        unblocks_count=fi.unblocks_count,
        downstream_depth=fi.downstream_depth,
        created_at=fi.created_at,
    )


def _frontier_result_to_model(fr: FrontierResult) -> _main.FrontierResultModel:
    """Convert a domain FrontierResult dataclass to its Pydantic model."""
    return _main.FrontierResultModel(
        runnable=[_frontier_item_to_model(i) for i in fr.runnable],
        blocked=[_frontier_item_to_model(i) for i in fr.blocked],
        frozen=[_frontier_item_to_model(i) for i in fr.frozen],
        wip_cap=fr.wip_cap,
        wip_active=fr.wip_active,
        conduct_eligible=[_frontier_item_to_model(i) for i in fr.conduct_eligible],
    )


def _scheduled_step_to_model(step) -> _main.ScheduledStepModel:
    """Convert a domain ScheduledStep to its Pydantic model."""
    gate_models = []
    for ge in step.gate_evaluations:
        gate_models.append(_main.GateEvaluationModel(
            blocking_item=ge.blocking_item,
            relation=ge.relation,
            gate_point=ge.gate_point,
            satisfaction=ge.satisfaction,
            satisfied=ge.satisfied,
            reason=ge.reason,
        ))
    return _main.ScheduledStepModel(
        item_id=step.item_id,
        item_type=step.item_type,
        status=step.status,
        title=step.title,
        priority=step.priority,
        next_step=step.next_step.value if hasattr(step.next_step, "value") else str(step.next_step),
        rank=step.rank,
        claim_state=step.claim_state.value if hasattr(step.claim_state, "value") else str(step.claim_state),
        gate_evaluations=gate_models,
        explanation=step.explanation,
        adapter=step.adapter,
        blocked_by=step.blocked_by,
        blocked_reasons=step.blocked_reasons,
        unblocks_count=step.unblocks_count,
        downstream_depth=step.downstream_depth,
        created_at=step.created_at,
    )


def _scheduler_result_to_model(sr) -> _main.SchedulerResultModel:
    """Convert a domain SchedulerResult to its Pydantic model."""
    conn = _main.get_db_readonly()
    try:
        project_scope = [resolve_project_slug(conn, int(pid)) for pid in sr.project_scope]
    finally:
        conn.close()
    return _main.SchedulerResultModel(
        project_scope=project_scope,
        sml_state=_main.SMLStateModel(
            coherent=sr.sml_state.coherent,
        ),
        selected_step=_scheduled_step_to_model(sr.selected_step) if sr.selected_step else None,
        ranked_steps=[_scheduled_step_to_model(s) for s in sr.ranked_steps],
        blocked_steps=[_scheduled_step_to_model(s) for s in sr.blocked_steps],
        exceptional_steps=[_scheduled_step_to_model(s) for s in sr.exceptional_steps],
        wip_cap=sr.wip_cap,
        wip_active=sr.wip_active,
        conduct_eligible=[_scheduled_step_to_model(s) for s in sr.conduct_eligible],
        frozen_steps=[_scheduled_step_to_model(s) for s in sr.frozen_steps],
    )


# ---------------------------------------------------------------------------
# Charge / Frontier endpoints
# ---------------------------------------------------------------------------


@router.get("/charge/frontier", response_model=_main.FrontierResultModel)
def api_charge_frontier(
    project: str = Query(default="yoke", description="Project to scope the frontier to."),
    wip_cap: int = Query(default=5, ge=1, le=100, description="WIP cap for conduct-eligible items."),
) -> Union[_main.FrontierResultModel, JSONResponse]:
    """Compute and return the runnable frontier for a project."""
    conn = _main.get_db_readonly()
    try:
        result = compute_domain_frontier(conn, project_scope=[project], wip_cap=wip_cap)
        return _frontier_result_to_model(result)
    except db_backend.operational_error_types(conn) as exc:
        if "database is locked" in str(exc).lower():
            return _main._error_response(503, "DB_BUSY", "Database is locked.")
        raise
    finally:
        conn.close()


@router.get("/charge/schedule", response_model=_main.SchedulerResultModel)
def api_charge_schedule(
    project: str = Query(default="yoke", description="Project to scope the schedule to."),
    wip_cap: int = Query(default=5, ge=1, le=100, description="WIP cap for conduct-eligible items."),
) -> Union[_main.SchedulerResultModel, JSONResponse]:
    """Compute the shared scheduler result for a project."""
    conn = _main.get_db_readonly()
    try:
        result = compute_schedule(conn, project_scope=[project], wip_cap=wip_cap)
        return _scheduler_result_to_model(result)
    except db_backend.operational_error_types(conn) as exc:
        if "database is locked" in str(exc).lower():
            return _main._error_response(503, "DB_BUSY", "Database is locked.")
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Dependency planning endpoints
# ---------------------------------------------------------------------------


class BlockerDetailModel(BaseModel):
    """Structured blocker detail from the shared planning kernel."""

    blocking_item: str
    blocking_status: Optional[str] = None
    gate_point: str
    satisfaction: str
    rationale: str = ""
    reason: str = ""


class ItemGateEvaluationModel(BaseModel):
    """Single-item gate evaluation result."""

    item_id: str
    gate_point: str
    is_blocked: bool
    unsatisfied_blockers: List[BlockerDetailModel] = Field(default_factory=list)


class PlanCandidateRequest(BaseModel):
    """Request body for candidate-set planning."""

    candidate_ids: List[str]
    gate_point: str


class BlockedCandidateModel(BaseModel):
    """A blocked candidate with its blocker details."""

    item_id: str
    blockers: List[BlockerDetailModel] = Field(default_factory=list)


class PlanResultModel(BaseModel):
    """Candidate-set planning result."""

    gate_point: str
    eligible: List[str] = Field(default_factory=list)
    blocked: List[BlockedCandidateModel] = Field(default_factory=list)
    has_cycle: bool = False
    cycle_items: List[str] = Field(default_factory=list)


@router.get("/dependencies/{item_id}/gate/{gate_point}")
async def evaluate_gate(item_id: str, gate_point: str):
    """Evaluate all dependencies for one item at a specific gate point."""
    conn = _main.get_db_readonly()
    try:
        result = evaluate_item_gate(conn, item_id, gate_point)
        return ItemGateEvaluationModel(
            item_id=result.item_id,
            gate_point=result.gate_point,
            is_blocked=result.is_blocked,
            unsatisfied_blockers=[
                BlockerDetailModel(**b.to_dict())
                for b in result.unsatisfied_blockers
            ],
        )
    except ValueError as exc:
        return _main._error_response(400, "INVALID_GATE_POINT", str(exc))
    finally:
        conn.close()


@router.post("/dependencies/plan")
async def plan_candidates(body: PlanCandidateRequest):
    """Plan a candidate set at a specific gate point."""
    conn = _main.get_db_readonly()
    try:
        result = plan_candidate_set(conn, body.candidate_ids, body.gate_point)
        return PlanResultModel(
            gate_point=result.gate_point,
            eligible=result.eligible,
            blocked=[
                BlockedCandidateModel(
                    item_id=c.item_id,
                    blockers=[BlockerDetailModel(**b.to_dict()) for b in c.blockers],
                )
                for c in result.blocked
            ],
            has_cycle=result.has_cycle,
            cycle_items=result.cycle_items,
        )
    except ValueError as exc:
        return _main._error_response(400, "INVALID_GATE_POINT", str(exc))
    finally:
        conn.close()
