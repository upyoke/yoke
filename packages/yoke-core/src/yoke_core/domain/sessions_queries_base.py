"""Session ID normalization and offer-compatibility filtering."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from . import db_backend
from .scheduler_types import is_assignable_claim_state
from .session_decision_lane_gate import evaluate_lane_gate
from .sessions_analytics import _NEXT_STEP_TO_PATH


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"

def normalize_claim_item_id(item_id: str) -> str:
    """Canonicalize numeric item IDs to bare numeric while preserving sentinels."""
    bare = item_id[4:] if item_id.upper().startswith("YOK-") else item_id
    if bare.isdigit():
        return bare.lstrip("0") or "0"
    return item_id


def normalize_session_item_id(item_id: str) -> str:
    """Canonicalize session-attribution item IDs to bare numeric when possible."""
    bare = item_id[4:] if item_id.upper().startswith("YOK-") else item_id
    if bare.isdigit():
        return bare.lstrip("0") or "0"
    return item_id


def display_claim_item_id(item_id: Optional[str]) -> Optional[str]:
    """Render internal numeric claim IDs back to display-only YOK-N form."""
    if item_id is None:
        return None
    normalized = normalize_claim_item_id(str(item_id))
    if normalized.isdigit():
        return f"YOK-{normalized}"
    return str(item_id)


def _claim_item_lookup_pair(item_id: str) -> tuple[str, str]:
    """Return the canonical storage value plus its legacy prefixed alias."""
    normalized = normalize_claim_item_id(item_id)
    if normalized.isdigit():
        return normalized, f"YOK-{normalized}"
    return normalized, normalized


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


def derive_required_path(item_type: str, status: str) -> Optional[str]:
    """Derive the canonical downstream path for claimed work.

    Uses the scheduler's ``_compute_next_step`` routing truth — the same
    status/type -> next_step mapping that charge already relies on.

    Returns the canonical path name (e.g., ``advance``, ``polish``,
    ``usher``) or ``None`` if the mapping cannot be resolved.
    """
    from .scheduler import _compute_next_step
    from .frontier import AdapterCategory, _STATUS_ADAPTER_MAP

    adapter = AdapterCategory.WAIT
    if status in _STATUS_ADAPTER_MAP:
        adapter = _STATUS_ADAPTER_MAP[status]

    result = _compute_next_step(item_type, status, adapter)
    ns = result.next_step
    if hasattr(ns, "value"):
        ns = ns.value
    return _NEXT_STEP_TO_PATH.get(str(ns))


def resolve_claimed_work_context(
    conn: Any,
    claim: Dict[str, Any],
) -> Dict[str, Optional[str]]:
    """Resolve current routing metadata for a raw claim row."""
    item_id = claim.get("item_id")
    epic_id = claim.get("epic_id")
    task_num = claim.get("task_num")
    item_type: Optional[str] = None
    status: Optional[str] = claim.get("status")
    required_path: Optional[str] = claim.get("required_path")

    lookup_id: Optional[int] = None
    if item_id:
        try:
            lookup_id = int(str(item_id).upper().replace("YOK-", ""))
        except ValueError:
            lookup_id = None
    elif epic_id is not None:
        lookup_id = int(epic_id)

    if lookup_id is not None:
        p = _p(conn)
        row = conn.execute(
            f"SELECT type, status FROM items WHERE id = {p}",
            (lookup_id,),
        ).fetchone()
        if row is not None:
            item_type = row["type"] or item_type
            status = row["status"] or status

    # Active epic-task claims always resume through conduct.
    if epic_id is not None and task_num is not None and not item_id:
        required_path = required_path or "conduct"
    elif required_path is None and item_type and status:
        required_path = derive_required_path(item_type, status)

    return {
        "item_type": item_type,
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


def _serialize_filtered_step(step: Any) -> Dict[str, Any]:
    """Serialize an incompatible ScheduledStep for downstream rendering.

    Captures the fields the decision engine and ``/yoke do`` loop need to
    explain a lane-policy mismatch to the operator: which items were dropped
    and what path they need.
    """
    next_step_val = getattr(step, "next_step", None)
    if hasattr(next_step_val, "value"):
        next_step_val = next_step_val.value
    claim_state_val = getattr(step, "claim_state", None)
    if hasattr(claim_state_val, "value"):
        claim_state_val = claim_state_val.value
    return {
        "item_id": getattr(step, "item_id", ""),
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
    compatible_ranked_steps: List[Any] = []
    incompatible_ranked_steps: List[Any] = []
    for step in schedule.ranked_steps:
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

    compatible_assignable_steps = [
        step
        for step in compatible_ranked_steps
        if is_assignable_claim_state(step.claim_state)
    ]

    schedule.lane_filtered_count = len(incompatible_ranked_steps)
    schedule.lane_filtered_items = [
        _serialize_filtered_step(step) for step in incompatible_ranked_steps
    ]
    schedule.ranked_steps = compatible_ranked_steps
    schedule.conduct_eligible = compatible_conduct_eligible
    schedule.selected_step = compatible_assignable_steps[0] if compatible_assignable_steps else None
    return schedule
