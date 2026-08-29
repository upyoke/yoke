"""Session ID normalization and offer-compatibility filtering."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from . import db_backend
from .scheduler_types import NextStep, is_assignable_claim_state
from .item_ref_render import ItemRefLookup, render_item_ref_lookup
from .session_offer_diagnostics import build_schedule_offer_diagnostics
from .session_decision_lane_gate import evaluate_lane_gate
from .sessions_analytics import _NEXT_STEP_TO_PATH
from .workflow_runtime import WorkflowRuntime, load_item_workflow_runtime


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def normalize_claim_item_id(item_id: Any) -> str:
    """Normalize an item id decoded from ``work_claims.scope``."""
    text = str(item_id)
    if text.isdigit():
        return text.lstrip("0") or "0"
    return text


def normalize_session_item_id(item_id: Any) -> str:
    """Normalize typed session item-id columns for comparisons."""
    text = str(item_id)
    if text.isdigit():
        return text.lstrip("0") or "0"
    return text


def display_claim_item_id(
    item_id: Optional[str],
    conn: Any = None,
) -> Optional[str]:
    """Render a claim's item id for display.

    The ``item_id`` key in ``work_claims.scope`` stores the internal bare
    ``items.id``. The ref
    an operator should see is project-scoped
    (``{projects.public_item_prefix}-{items.project_sequence}``), which can
    diverge from the internal id. When ``conn`` is supplied, resolve the true
    public ref via ``render_item_ref`` (which itself falls back to a
    prefix+id string when the item row is missing). Without a connection —
    routing callers that resolve work back by internal id — return the bare
    internal-id string; a prefixed form here would leak a wrong public ref
    for items whose sequence diverges from the internal id.
    """
    if item_id is None:
        return None
    normalized = normalize_claim_item_id(str(item_id))
    if normalized.isdigit():
        if conn is not None:
            from .project_identity import render_item_ref

            return render_item_ref(conn, int(normalized))
        return normalized
    return str(item_id)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _row_to_dict(row: Any) -> Dict[str, Any]:
    return dict(row)


def _required_path_for_step(step: Any) -> Optional[str]:
    """Return the canonical downstream path name for a scheduled step."""
    next_step = getattr(step, "next_step", None)
    if next_step is None:
        return None
    if hasattr(next_step, "value"):
        next_step = next_step.value
    return _NEXT_STEP_TO_PATH.get(str(next_step))


# ---------------------------------------------------------------------------
# Routing / compatibility
# ---------------------------------------------------------------------------


def derive_required_path(
    workflow: WorkflowRuntime,
    status: str,
) -> Optional[str]:
    """Derive the canonical downstream path for claimed work.

    Uses the scheduler's definition-selected routing truth.

    Returns the canonical path name (e.g., ``advance``, ``polish``,
    ``usher``) or ``None`` if the mapping cannot be resolved.
    """
    from .frontier_classify import classify_next_action
    from .scheduler import _compute_next_step

    adapter = classify_next_action(workflow, status)
    result = _compute_next_step(
        adapter,
        probe_path_claim_activation=(workflow.requires_item_path_claim_probe(status)),
    )
    ns = result.next_step
    if hasattr(ns, "value"):
        ns = ns.value
    return _NEXT_STEP_TO_PATH.get(str(ns))


def resolve_claimed_work_context(
    conn: Any,
    claim: Dict[str, Any],
) -> Dict[str, Any]:
    """Resolve current routing metadata for a raw claim row."""
    from .work_claim_targets import from_row as target_from_row
    target = target_from_row(claim)
    item_id = target.item_id
    epic_id = target.epic_id
    task_num = target.task_num
    workflow: Optional[WorkflowRuntime] = None
    status: Optional[str] = claim.get("status")
    required_path: Optional[str] = claim.get("required_path")

    lookup_id: Optional[int] = None
    if item_id:
        try:
            lookup_id = int(item_id)
        except (TypeError, ValueError):
            lookup_id = None
    elif epic_id is not None:
        lookup_id = int(epic_id)

    if lookup_id is not None:
        p = _p(conn)
        row = conn.execute(
            f"SELECT status FROM items WHERE id = {p}",
            (lookup_id,),
        ).fetchone()
        if row is not None:
            status = row["status"] or status
            workflow = load_item_workflow_runtime(conn, lookup_id)

    # Active epic-task claims always resume through conduct.
    if epic_id is not None and task_num is not None and not item_id:
        required_path = required_path or "conduct"
    elif required_path is None and workflow is not None and status:
        required_path = derive_required_path(workflow, status)

    return {
        "workflow_id": workflow.workflow_id if workflow else None,
        "workflow_version_id": workflow.workflow_version_id if workflow else None,
        "workflow_version": workflow.version if workflow else None,
        "status": status,
        "required_path": required_path,
    }


def _step_is_compatible_with_offer(
    step: Any,
    *,
    execution_lane: str,
    supported_paths: Optional[List[str]],
    lane_allowed_paths: Optional[Dict[str, List[str]]],
) -> bool:
    """Return True when a scheduled step can run in this session.

    Compatibility is the intersection of:
    - server-derived supported paths (`supported_paths`)
    - Yoke core lane policy (`lane_allowed_paths`)
    """
    required_path = _required_path_for_step(step)
    if required_path is None:
        return True

    if supported_paths and required_path not in supported_paths:
        return False

    gate = evaluate_lane_gate(
        execution_lane=execution_lane,
        required_path=required_path,
        lane_allowed_paths=lane_allowed_paths,
    )
    if gate.is_blocked:
        return False

    return True


def _serialize_filtered_step(step: Any, public_ref: ItemRefLookup) -> Dict[str, Any]:
    """Serialize an incompatible ScheduledStep for downstream rendering.

    Captures the fields the decision engine and ``/yoke do`` loop need to
    explain a lane-policy mismatch to the operator: which items were dropped
    and what path they need. ``item_id`` is operator-facing: rendered from
    the caller's already-resolved public-ref lookup.
    """
    next_step_val = getattr(step, "next_step", None)
    if hasattr(next_step_val, "value"):
        next_step_val = next_step_val.value
    claim_state_val = getattr(step, "claim_state", None)
    if hasattr(claim_state_val, "value"):
        claim_state_val = claim_state_val.value
    raw_item_id = getattr(step, "item_id", "")
    return {
        "item_id": public_ref(raw_item_id),
        "title": getattr(step, "title", ""),
        "status": getattr(step, "status", ""),
        "next_step": next_step_val,
        "required_path": _required_path_for_step(step),
        "rank": getattr(step, "rank", 0),
        "claim_state": claim_state_val,
    }


def _filter_schedule_for_offer(
    schedule: Any,
    *,
    execution_lane: str,
    supported_paths: Optional[List[str]],
    lane_allowed_paths: Optional[Dict[str, List[str]]],
    conn: Any = None,
) -> Any:
    """Filter a scheduler result down to work runnable by this offer.

    The shared scheduler computes the global frontier. Session offering then
    narrows that frontier to the subset the current lane+harness can actually
    execute before it claims work. This prevents a compatible lower-ranked
    item from being masked by a globally higher-ranked but incompatible item.

    Items dropped by compatibility filtering are preserved on
    ``schedule.lane_filtered_items`` so the decision engine can explain the
    mismatch to the operator instead of silently routing to FEED.
    """
    candidate_steps = list(schedule.ranked_steps)
    compatible_ranked_steps: List[Any] = []
    incompatible_ranked_steps: List[Any] = []
    for step in candidate_steps:
        if _step_is_compatible_with_offer(
            step,
            execution_lane=execution_lane,
            supported_paths=supported_paths,
            lane_allowed_paths=lane_allowed_paths,
        ):
            compatible_ranked_steps.append(step)
        else:
            incompatible_ranked_steps.append(step)

    compatible_conduct_eligible = [
        step
        for step in schedule.conduct_eligible
        if _step_is_compatible_with_offer(
            step,
            execution_lane=execution_lane,
            supported_paths=supported_paths,
            lane_allowed_paths=lane_allowed_paths,
        )
    ]

    conduct_eligible_ids = {step.item_id for step in compatible_conduct_eligible}
    wip_filtered_steps = [
        step
        for step in compatible_ranked_steps
        if step.next_step == NextStep.CONDUCT
        and step.item_id not in conduct_eligible_ids
    ]
    wip_surviving_steps = [
        step for step in compatible_ranked_steps if step not in wip_filtered_steps
    ]
    claim_filtered_steps = [
        step
        for step in wip_surviving_steps
        if not is_assignable_claim_state(step.claim_state)
    ]
    compatible_assignable_steps = [
        step
        for step in wip_surviving_steps
        if is_assignable_claim_state(step.claim_state)
    ]

    schedule.lane_filtered_count = len(incompatible_ranked_steps)
    lane_filtered_ref = render_item_ref_lookup(
        conn,
        (getattr(step, "item_id", "") for step in incompatible_ranked_steps),
    )
    schedule.lane_filtered_items = [
        _serialize_filtered_step(step, lane_filtered_ref)
        for step in incompatible_ranked_steps
    ]
    schedule.offer_diagnostics = build_schedule_offer_diagnostics(
        candidate_steps=candidate_steps,
        compatible_steps=compatible_ranked_steps,
        lane_filtered_steps=incompatible_ranked_steps,
        wip_filtered_steps=wip_filtered_steps,
        claim_filtered_steps=claim_filtered_steps,
        schedule=schedule,
        execution_lane=execution_lane,
        lane_allowed_paths=lane_allowed_paths,
        conn=conn,
    )
    schedule.ranked_steps = wip_surviving_steps
    schedule.conduct_eligible = compatible_conduct_eligible
    schedule.selected_step = (
        compatible_assignable_steps[0] if compatible_assignable_steps else None
    )
    return schedule
