"""Scheduler telemetry emission."""

from __future__ import annotations

import logging
from typing import Any, Mapping, Optional

from .scheduler_skip_reasons import SKIP_REASONS
from .scheduler_types import SchedulerResult

_logger = logging.getLogger(__name__)

def _emit_frontier_step_selected(
    conn: Any,
    result: SchedulerResult,
    session_id: Optional[str],
) -> None:
    """Emit a FrontierStepSelected event after the scheduler finalizes."""
    try:
        from .events import emit_event

        selected = result.selected_step
        if selected is None:
            return

        # Top-3 alternatives (excluding the selected item)
        alternatives = [
            {
                "item_id": s.item_id,
                "next_step": s.next_step.value,
                "rank": s.rank,
                "claim_state": s.claim_state.value,
            }
            for s in result.ranked_steps[:4]
            if s.item_id != selected.item_id
        ][:3]

        ctx: dict[str, Any] = {
            "selected_item": selected.item_id,
            "next_step": selected.next_step.value,
            "rank": selected.rank,
            "claim_state": selected.claim_state.value,
            "explanation": selected.explanation,
            "alternatives": alternatives,
        }
        if selected.routing_override is not None:
            ctx.update(selected.routing_override.to_context_dict())
        from .frontier_compute import _canonical_project_label

        ctx["project_scope"] = list(result.project_scope)
        emit_event(
            "FrontierStepSelected", event_kind="workflow",
            event_type="scheduler_selection", source_type="backend",
            session_id=session_id or "", item_id=selected.item_id,
            project=_canonical_project_label(conn, result.project_scope), context=ctx,
        )
    except Exception as exc:
        _logger.debug("FrontierStepSelected emission failed: %s", exc)


def emit_scheduler_offer_skipped(
    *,
    session_id: str,
    skip_reason: str,
    chain_step: int,
    project: str = "yoke",
    item_id: Optional[str] = None,
    process_key: Optional[str] = None,
    recommended_action: Optional[str] = None,
    current_status: Optional[str] = None,
    holder_session_id: Optional[str] = None,
    claim_id: Optional[int] = None,
    claimed_at: Optional[str] = None,
    config_key: Optional[str] = None,
    extra: Optional[Mapping[str, Any]] = None,
) -> None:
    """Emit ``SchedulerOfferSkipped`` for a canonical skip reason.

    Valid reasons live in
    :data:`yoke_core.domain.scheduler_skip_reasons.SKIP_REASONS`;
    holder fields may be omitted when lookup fails.
    """
    if skip_reason not in SKIP_REASONS:
        raise ValueError(f"invalid SchedulerOfferSkipped skip_reason: {skip_reason!r}")
    try:
        from .events import emit_event

        ctx: dict[str, Any] = {
            "session_id": session_id, "skip_reason": skip_reason,
            "chain_step": chain_step,
        }
        for k, v in (
            ("item_id", item_id), ("process_key", process_key),
            ("recommended_action", recommended_action),
            ("current_status", current_status),
            ("claim_holder_session_id", holder_session_id),
            ("claim_id", claim_id), ("claimed_at", claimed_at),
            ("config_key", config_key),
        ):
            if v is not None:
                ctx[k] = v
        if extra:
            for k, v in extra.items():
                ctx.setdefault(k, v)
        emit_event(
            "SchedulerOfferSkipped", event_kind="audit",
            event_type="scheduler_selection", source_type="backend",
            session_id=session_id, item_id=item_id,
            project=project, context=ctx,
        )
    except Exception as exc:
        _logger.debug("SchedulerOfferSkipped emission failed: %s", exc)


def emit_chain_decline_overridden(
    *,
    session_id: str,
    checkpoint_step: int,
    max_chain_steps: int,
    rationale: str,
    project: str = "yoke",
    action: Optional[str] = None,
    item_id: Optional[str] = None,
    override_flag: str = "force_chain_end",
) -> None:
    """Emit ``ChainDeclineOverridden`` when ``session-end --override-chain-end`` plus a rationale bypasses the chain-budget guard."""
    try:
        from .events import emit_event

        emit_event(
            "ChainDeclineOverridden",
            event_kind="audit",
            event_type="chain_checkpoint",
            source_type="backend",
            session_id=session_id,
            item_id=item_id,
            project=project,
            context={
                "session_id": session_id,
                "checkpoint_step": checkpoint_step,
                "max_chain_steps": max_chain_steps,
                "rationale": rationale,
                "action": action,
                "item_id": item_id,
                "override_flag": override_flag,
            },
        )
    except Exception as exc:
        _logger.debug("ChainDeclineOverridden emission failed: %s", exc)


def emit_chain_end_deferred(
    *,
    session_id: str,
    triggered_by: str,
    checkpoint_step: int,
    max_chain_steps: int,
    handler_outcome: Optional[str],
    chainable: bool,
    project: str = "yoke",
    action: Optional[str] = None,
    item_id: Optional[str] = None,
    last_release_at: Optional[str] = None,
) -> None:
    """Emit ``ChainEndDeferred`` when ``session-end-if-empty`` declines to end a session because a chainable checkpoint still has budget remaining.

    Structural counterpart to :func:`emit_chain_decline_overridden`: the
    Stop hook routinely fires after the loop has released its work claim
    mid-chain (at the ``handoff-to-polish`` / ``handoff-to-usher``
    handoff) but before the next routed offer can run. The
    cleanup helper sees ``claim_count == 0`` and previously ended the
    session silently; this event records the structural decline so an
    operator (or doctor) can audit chains the guard protected.
    """
    try:
        from .events import emit_event

        emit_event(
            "ChainEndDeferred",
            event_kind="audit",
            event_type="chain_checkpoint",
            source_type="backend",
            session_id=session_id,
            item_id=item_id,
            project=project,
            context={
                "session_id": session_id,
                "triggered_by": triggered_by,
                "checkpoint_step": checkpoint_step,
                "max_chain_steps": max_chain_steps,
                "handler_outcome": handler_outcome,
                "chainable": chainable,
                "action": action,
                "item_id": item_id,
                "last_release_at": last_release_at,
            },
        )
    except Exception as exc:
        _logger.debug("ChainEndDeferred emission failed: %s", exc)


def emit_harness_session_end_deferred(
    *,
    session_id: str,
    defer_reason: str,
    agent_presence_evidence: Mapping[str, Any],
    active_claim_count: int,
    project: str = "yoke",
    claim_details: Optional[list[Mapping[str, Any]]] = None,
    item_id: Optional[str] = None,
) -> None:
    """Emit ``HarnessSessionEndDeferred`` for a transient SessionEnd defense.

    Fired by ``end_session(release_claims=True)`` when the shared
    destructive guard returns ``defer=True`` (heartbeat fresh within the
    recovery window OR chainable checkpoint with remaining budget). The
    claims stay active and no terminal ``HarnessSessionEnded`` row is
    written for this signal.
    """
    try:
        from .events import emit_event

        emit_event(
            "HarnessSessionEndDeferred",
            event_kind="system",
            event_type="session_lifecycle",
            source_type="backend",
            session_id=session_id,
            project=project,
            item_id=item_id,
            context={
                "session_id": session_id,
                "defer_reason": defer_reason,
                "agent_presence_evidence": dict(agent_presence_evidence),
                "active_claim_count": active_claim_count,
                "claim_details": list(claim_details or []),
            },
        )
    except Exception as exc:
        _logger.debug("HarnessSessionEndDeferred emission failed: %s", exc)


def emit_session_reactivation_reacquired_claims(
    *,
    session_id: str,
    reacquired_count: int,
    conflict_count: int,
    claim_details: list[Mapping[str, Any]],
    project: str = "yoke",
) -> None:
    """Emit ``SessionReactivationReacquiredClaims`` after auto-reacquire."""
    try:
        from .events import emit_event

        emit_event(
            "SessionReactivationReacquiredClaims",
            event_kind="system",
            event_type="session_lifecycle",
            source_type="backend",
            session_id=session_id,
            project=project,
            context={
                "session_id": session_id,
                "reacquired_count": reacquired_count,
                "conflict_count": conflict_count,
                "claim_details": list(claim_details),
            },
        )
    except Exception as exc:
        _logger.debug("SessionReactivationReacquiredClaims emission failed: %s", exc)


def emit_harness_session_resume_block_shown(
    *,
    session_id: str,
    harness_event: str,
    reactivation_event_id: Optional[int],
    reacquired: bool,
    advisory_only: bool,
    project: str = "yoke",
) -> None:
    """Emit the once-per-reactivation marker the slim resume block consumed."""
    try:
        from .events import emit_event

        emit_event(
            "HarnessSessionResumeBlockShown",
            event_kind="system",
            event_type="session_lifecycle",
            source_type="backend",
            session_id=session_id,
            project=project,
            context={
                "session_id": session_id,
                "harness_event": harness_event,
                "reactivation_event_id": reactivation_event_id,
                "reacquired": reacquired,
                "advisory_only": advisory_only,
            },
        )
    except Exception as exc:
        _logger.debug("HarnessSessionResumeBlockShown emission failed: %s", exc)


def emit_chain_budget_unused(
    *,
    session_id: str,
    step: int,
    max_chain_steps: int,
    remaining_budget: int,
    terminal_reason: str,
    candidate_trail: Optional[list[Mapping[str, Any]]] = None,
    project: str = "yoke",
) -> None:
    """Emit ``ChainBudgetUnused`` on a terminal /yoke do checkpoint with budget remaining.

    Terminal reasons: ``all_candidates_blocked``, ``all_candidates_stale``,
    ``all_candidates_disabled_process``, ``mixed_unavailable``.
    """
    try:
        from .events import emit_event

        emit_event(
            "ChainBudgetUnused",
            event_kind="workflow",
            event_type="chain_checkpoint",
            source_type="backend",
            session_id=session_id,
            project=project,
            context={
                "session_id": session_id,
                "step": step,
                "max_chain_steps": max_chain_steps,
                "remaining_budget": remaining_budget,
                "terminal_reason": terminal_reason,
                "candidate_trail": list(candidate_trail or []),
            },
        )
    except Exception as exc:
        _logger.debug("ChainBudgetUnused emission failed: %s", exc)
