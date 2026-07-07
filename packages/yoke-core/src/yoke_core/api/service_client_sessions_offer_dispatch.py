"""Decision-engine dispatch for ``cmd_session_offer``.

The 4-branch dispatch — resume / no-work-wait / schedule_result / empty
frontier — lives here so the parent ``cmd_session_offer`` in
``service_client_sessions_offer.py`` stays under the file-line limit. Each
branch ends in a single ``decide_next_action`` call (or a no-work-wait
short-circuit) and returns ``(result, drift_dict)``.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

from yoke_core.api.service_client_shared import (
    ClaimedWork,
    FrontierState,
    SessionOffer,
    build_drift_review_failure_action,
    compute_schedule,
    display_claim_item_id,
    normalize_claim_item_id,
    read_chain_checkpoint,
    resolve_claimed_work_context,
)
from yoke_core.api.service_client_sessions_offer_helpers import (
    build_no_work_wait_action,
    should_return_no_work_wait,
)


def _resolve_build_frontier_state(resolve_monkeypatchable: Callable[[str], Any]):
    """Resolve the frontier-state builder honoring caller monkeypatches.

    Tests monkeypatch ``_build_frontier_state_from_schedule`` on the parent
    ``service_client_sessions_offer`` module. Look it up via the parent's
    module attribute first; fall back to the canonical leaf import when no
    patched binding is registered.
    """
    import sys

    parent = sys.modules.get("yoke_core.api.service_client_sessions_offer")
    if parent is not None:
        binding = getattr(parent, "_build_frontier_state_from_schedule", None)
        if binding is not None:
            return binding
    # Fall back to the canonical leaf import.
    from yoke_core.api.service_client_sessions_frontier import (
        build_frontier_state_from_schedule,
    )
    return build_frontier_state_from_schedule


def dispatch_decision_engine(
    conn: Any,
    *,
    offer: SessionOffer,
    ownership: Dict[str, Any],
    project_scope: List[int],
    routing_config,
    effective_policy,
    session_id: str,
    workspace: str,
    step: int,
    resolve_monkeypatchable: Callable[[str], Any],
) -> Tuple[Any, Optional[Dict[str, Any]]]:
    """Walk the 4-branch dispatch and return ``(result, drift_dict)``.

    The dispatch always produces a ``NextAction`` result. ``drift_dict`` is
    populated when the resume / schedule_result branches succeed in calling
    ``assess_post_delivery_drift`` — the caller uses it to decide whether to
    emit the matching ``DriftReviewCompleted`` event.
    """
    drift_dict: Optional[Dict[str, Any]] = None

    if ownership["action_hint"] == "resume":
        active_claims: List[ClaimedWork] = []
        for claim in ownership["claims"]:
            claim_ctx = resolve_claimed_work_context(conn, claim)
            active_claims.append(
                ClaimedWork(
                    item_id=display_claim_item_id(claim.get("item_id")),
                    epic_id=claim.get("epic_id"),
                    task_num=claim.get("task_num"),
                    status=claim_ctx.get("status"),
                    item_type=claim_ctx.get("item_type"),
                    required_path=claim_ctx.get("required_path"),
                )
            )

        last_step: Optional[Dict[str, Any]] = None
        checkpoint = read_chain_checkpoint(conn, session_id)
        if checkpoint:
            last_step = {
                "action": checkpoint.get("action"),
                "item_id": checkpoint.get("item_id"),
                "task_num": checkpoint.get("task_num"),
                "status": checkpoint.get("status"),
                "required_path": checkpoint.get("required_path"),
                "handler_outcome": checkpoint.get("handler_outcome"),
                "pre_status": checkpoint.get("pre_status"),
            }

        schedule = compute_schedule(
            conn, project_scope=project_scope, session_id=session_id, workspace=workspace,
        )
        try:
            drift = resolve_monkeypatchable("assess_post_delivery_drift")(conn, project_scope)
        except RuntimeError as exc:
            return build_drift_review_failure_action(session_id, str(exc)), None

        drift_dict = drift.to_dict() if drift else None
        frontier = _resolve_build_frontier_state(resolve_monkeypatchable)(
            schedule,
            drift_review_dict=drift_dict,
            last_completed_step=last_step,
        )
        result = resolve_monkeypatchable("decide_next_action")(
            offer,
            frontier,
            active_claims,
            lane_allowed_paths=routing_config.lane_allowed_paths,
            process_offer_policy=effective_policy,
        )
        return result, drift_dict

    if should_return_no_work_wait(ownership, step):
        # every candidate hit a skip so the offer has no claim.
        # Construct WAIT directly rather than letting the schedule_result
        # branch hand decide_next_action a stale runnable list.
        result = build_no_work_wait_action(
            session_id=session_id, ownership=ownership, step=step,
        )
        return result, None

    if ownership["schedule_result"] is not None:
        schedule = ownership["schedule_result"]
        try:
            drift = resolve_monkeypatchable("assess_post_delivery_drift")(conn, project_scope)
        except RuntimeError as exc:
            return build_drift_review_failure_action(session_id, str(exc)), None

        drift_dict = drift.to_dict() if drift else None
        # drop same-offer skipped item ids from the
        # frontier so the engine cannot pick what ownership skipped.
        skip_ids = {
            normalize_claim_item_id(str(entry.get("item_id")))
            for entry in (ownership.get("chain_skip_memory") or [])
            if entry.get("item_id")
        }
        frontier = _resolve_build_frontier_state(resolve_monkeypatchable)(
            schedule,
            drift_review_dict=drift_dict,
            skip_memory_item_ids=skip_ids or None,
        )
        result = resolve_monkeypatchable("decide_next_action")(
            offer,
            frontier,
            None,
            lane_allowed_paths=routing_config.lane_allowed_paths,
            process_offer_policy=effective_policy,
        )
        return result, drift_dict

    frontier = FrontierState()
    result = resolve_monkeypatchable("decide_next_action")(
        offer,
        frontier,
        None,
        lane_allowed_paths=routing_config.lane_allowed_paths,
        process_offer_policy=effective_policy,
    )
    return result, drift_dict


__all__ = ["dispatch_decision_engine"]
