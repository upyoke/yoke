"""Shared frontier-step scheduler for the Yoke core."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from yoke_core.domain import db_backend

from .frontier import AdapterCategory, FrontierResult, compute_frontier as compute_raw_frontier
from .project_scope import normalize_project_scope
from .scheduler_claims import _evaluate_claim_states
from .scheduler_events import _emit_frontier_step_selected, _logger
from .scheduler_routing import _EPIC_ADAPTER_MAP, _StepResult, _compute_next_step
from .scheduler_types import (
    ClaimState,
    GateEvaluation,
    NextStep,
    SMLState,
    ScheduledStep,
    SchedulerResult,
    SML_FILES,
    is_assignable_claim_state,
)

def _compute_sml_state(
    conn: Any,
    project_scope: List[int],
    workspace: Optional[str] = None,
) -> SMLState:
    """Compute truthful SML coherence.

    Coherence: all four SML files must exist.  Staleness computation was
    removed — the post-delivery drift-review model replaces
    ambient stale-bit decisioning.
    """
    if workspace:
        ws_path = Path(workspace)
    else:
        # Default: repo root relative to this file
        from yoke_core.api.repo_root import find_repo_root

        ws_path = find_repo_root(Path(__file__))

    for fname in SML_FILES:
        if not (ws_path / fname).is_file():
            return SMLState(coherent=False)

    return SMLState(coherent=True)


# ---------------------------------------------------------------------------
# Exceptional-state visibility (failed items)
# ---------------------------------------------------------------------------

_FAILED_STATUS = "failed"


def _query_exceptional_items(
    conn: Any,
    project_scope: List[int],
) -> List[Dict[str, Any]]:
    """Query items in failed status across the given project scope."""
    if not project_scope:
        return []
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    placeholders = ", ".join(p for _ in project_scope)
    try:
        rows = conn.execute(
            f"""SELECT id, title, status, priority, project_id, type, created_at
               FROM items
               WHERE project_id IN ({placeholders})
                 AND status = {p}
                 AND (frozen IS NULL OR frozen = 0)""",
            (*project_scope, _FAILED_STATUS),
        ).fetchall()
        return [dict(r) for r in rows] if rows else []
    except db_backend.operational_error_types(conn):
        if db_backend.connection_is_postgres(conn):
            try:
                conn.rollback()
            except Exception:
                pass
        return []
    except IndexError:
        return []


# ---------------------------------------------------------------------------
# Main entry point — compute_schedule
# ---------------------------------------------------------------------------


def compute_schedule(
    conn: Any,
    project_scope: List[Union[int, str]],
    wip_cap: int = 5,
    session_id: Optional[str] = None,
    workspace: Optional[str] = None,
) -> SchedulerResult:
    """Compute the shared frontier-step schedule across a project scope.

    This is the single entry point consumed by both ``/yoke do``
    (session-offer) and ``/yoke charge``.

    Args:
        conn: SQLite connection (read-only access sufficient).
        project_scope: Numeric project ids in scope for this schedule. Slugs are
            accepted for CLI/API boundary callers and resolved before SQL.
        wip_cap: Maximum number of conduct-eligible items.
        session_id: Optional session ID for claim-state evaluation.
        workspace: Optional workspace path for SML file checks.

    Returns:
        A ``SchedulerResult`` with the full scheduling context.
    """
    project_scope = normalize_project_scope(conn, project_scope)

    # 1. Compute raw frontier (from frontier.py — handles deps, ranking,
    #    frozen, WIP cap, adapter classification)
    raw: FrontierResult = compute_raw_frontier(
        conn,
        project_scope=project_scope,
        wip_cap=wip_cap,
        session_id=session_id,
    )

    # 2. Compute SML state
    sml = _compute_sml_state(conn, project_scope, workspace=workspace)

    # 3. Collect all item IDs for claim evaluation
    all_item_ids = (
        [fi.item_id for fi in raw.runnable]
        + [fi.item_id for fi in raw.blocked]
    )

    # 4. Evaluate claim states
    claims = _evaluate_claim_states(conn, all_item_ids, session_id=session_id)

    conduct_eligible_ids = {fi.item_id for fi in raw.conduct_eligible}

    # 5. Convert runnable FrontierItems to ScheduledSteps with type-aware next_step
    ranked_steps: List[ScheduledStep] = []
    for rank_idx, fi in enumerate(raw.runnable):
        # Strip the "YOK-" prefix when present so the probe gets a bare int.
        _bare_id = fi.item_id
        if isinstance(_bare_id, str) and _bare_id.startswith("YOK-"):
            _bare_id = _bare_id[4:]
        try:
            _probe_item_id = int(_bare_id)
        except (TypeError, ValueError):
            _probe_item_id = None
        step_result = _compute_next_step(
            fi.item_type, fi.status, fi.adapter,
            conn=conn, item_id=_probe_item_id,
        )
        step = ScheduledStep(
            item_id=fi.item_id,
            item_type=fi.item_type,
            status=fi.status,
            title=fi.title,
            priority=fi.priority,
            next_step=step_result.next_step,
            rank=rank_idx,
            claim_state=claims.get(fi.item_id, ClaimState.UNCLAIMED),
            explanation=f"Ranked #{rank_idx + 1}: {step_result.next_step.value} for {fi.item_type} in {fi.status}",
            adapter=fi.adapter.value if isinstance(fi.adapter, AdapterCategory) else str(fi.adapter),
            blocked_by=fi.blocked_by,
            blocked_reasons=fi.blocked_reasons,
            unblocks_count=fi.unblocks_count,
            downstream_depth=fi.downstream_depth,
            created_at=fi.created_at,
            routing_override=step_result.routing_override,
        )
        ranked_steps.append(step)

    # 6. Convert blocked FrontierItems to ScheduledSteps
    blocked_steps: List[ScheduledStep] = []
    for fi in raw.blocked:
        gate_evals: List[GateEvaluation] = []
        # Only typed dependency-edge blockers produce GateEvaluation rows.
        # Non-edge causes (idea_incomplete, operator-flagged, legacy
        # status='blocked' drift) carry no gate point or blocking item;
        # blocked_reasons is the operator-facing message channel for those.
        if fi.blocker_details:
            for detail in fi.blocker_details:
                # `evaluate_batch_gates` populates blocking_item for every
                # real edge; the "unknown" default is a defensive fallback
                # that should never fire.
                gate_evals.append(GateEvaluation(
                    blocking_item=detail.get("blocking_item", "unknown"),
                    relation="blocker",
                    gate_point=detail.get("gate_point", "activation"),
                    satisfaction=detail.get("satisfaction", "status:done"),
                    satisfied=False,
                    reason=detail.get("reason", ""),
                    rationale=detail.get("rationale", ""),
                ))
        step = ScheduledStep(
            item_id=fi.item_id,
            item_type=fi.item_type,
            status=fi.status,
            title=fi.title,
            priority=fi.priority,
            next_step=NextStep.WAIT,
            claim_state=claims.get(fi.item_id, ClaimState.UNCLAIMED),
            gate_evaluations=gate_evals,
            explanation=f"Blocked: {'; '.join(fi.blocked_reasons)}" if fi.blocked_reasons else "Blocked",
            adapter=fi.adapter.value if isinstance(fi.adapter, AdapterCategory) else str(fi.adapter),
            blocked_by=fi.blocked_by,
            blocked_reasons=fi.blocked_reasons,
            unblocks_count=fi.unblocks_count,
            downstream_depth=fi.downstream_depth,
            created_at=fi.created_at,
        )
        blocked_steps.append(step)

    # 7. Query exceptional items (failed)
    exceptional_steps: List[ScheduledStep] = []
    exceptional_items = _query_exceptional_items(conn, project_scope)
    for ei in exceptional_items:
        item_id_str = f"YOK-{ei['id']}"
        exceptional_steps.append(ScheduledStep(
            item_id=item_id_str,
            item_type=ei.get("type", "issue"),
            status=ei.get("status", "failed"),
            title=ei.get("title", ""),
            priority=ei.get("priority", "medium"),
            next_step=NextStep.WAIT,
            explanation=f"Exceptional: item is in {ei.get('status', 'failed')} status",
            created_at=ei.get("created_at", ""),
        ))

    # 8. Convert frozen items
    frozen_steps: List[ScheduledStep] = []
    for fi in raw.frozen:
        frozen_steps.append(ScheduledStep(
            item_id=fi.item_id,
            item_type=fi.item_type,
            status=fi.status,
            title=fi.title,
            priority=fi.priority,
            next_step=NextStep.WAIT,
            explanation="Frozen — excluded from scheduling",
            created_at=fi.created_at,
        ))

    # 9. Convert conduct-eligible items
    conduct_eligible: List[ScheduledStep] = []
    for step in ranked_steps:
        if step.item_id in conduct_eligible_ids:
            conduct_eligible.append(step)

    # 10. Select the highest-ranked assignable step.
    #     Assignability is owned by ``is_assignable_claim_state``
    #     (scheduler_types). CLAIMED_BY_STALE items are reclaimable — treated
    #     as assignable so stale sessions never block forward progress.
    selected: Optional[ScheduledStep] = None
    for step in ranked_steps:
        # conduct_eligible_ids gates epic conduct eligibility only.
        # ADVANCE items (issue-workflow-type) route to /yoke advance and do NOT
        # go through the conduct pipeline, so they must not be filtered here
        # .
        if step.next_step == NextStep.CONDUCT and step.item_id not in conduct_eligible_ids:
            continue
        if is_assignable_claim_state(step.claim_state):
            selected = step
            break

    result = SchedulerResult(
        project_scope=list(project_scope),
        sml_state=sml,
        selected_step=selected,
        ranked_steps=ranked_steps,
        blocked_steps=blocked_steps,
        exceptional_steps=exceptional_steps,
        wip_cap=raw.wip_cap,
        wip_active=raw.wip_active,
        conduct_eligible=conduct_eligible,
        frozen_steps=frozen_steps,
    )

    # Emit FrontierStepSelected telemetry
    _emit_frontier_step_selected(conn, result, session_id)

    return result

__all__ = [
    "NextStep",
    "ClaimState",
    "SML_FILES",
    "SMLState",
    "GateEvaluation",
    "ScheduledStep",
    "SchedulerResult",
    "_EPIC_ADAPTER_MAP",
    "_StepResult",
    "_compute_next_step",
    "_evaluate_claim_states",
    "_compute_sml_state",
    "_query_exceptional_items",
    "compute_schedule",
    "_emit_frontier_step_selected",
    "_logger",
    "Path",
]
