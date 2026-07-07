"""Candidate walk for ``session_offer_with_ownership``.

The selection logic — try the scheduler's top candidate, revalidate, attempt
the claim, recompute-and-pin on success, skip on conflict or staleness, move
to the next candidate — lives here so the parent function in
``sessions_offer.py`` stays under the file-line limit. The candidate walk is
the self-contained subroutine of the offer flow: it owns the within-chain
skip memory, the pre/post-claim revalidation, and the up-to-three claim
attempts.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from .frontier_compute import _canonical_project_label
from .scheduler_skip_reasons import SKIP_REASON_STALE_LIFECYCLE_POST_CLAIM
from .sessions_analytics import SessionError
from .sessions_lifecycle import claim_work
from .sessions_lifecycle_release import release_item_claim_for_execution
from .sessions_offer_claim_pin import recompute_and_pin_for_claim
from .sessions_offer_revalidation import (
    holder_session_for_item,
    record_offer_skip,
    revalidate_candidate_status,
)
from .sessions_queries import normalize_claim_item_id
from .sessions_queries_chain import read_chain_skip_memory
from .sessions_render import reclaim_stale_item_claims

logger = logging.getLogger(__name__)


def acquire_claim_from_candidates(
    conn: Any,
    *,
    session_id: str,
    schedule,
    step: int,
    project_scope: List[int],
    wip_cap: int,
    workspace: str,
    authoritative_lane: str,
    supported_paths: List[str],
    lane_allowed_paths: Optional[Dict[str, List[str]]],
) -> Tuple[Any, Optional[Dict[str, Any]]]:
    """Walk the scheduler candidates and acquire one exclusive claim.

    Returns ``(schedule, new_claim)``. ``schedule`` is the possibly-pinned
    schedule (``recompute_and_pin_for_claim`` may return a fresh result when
    the acquired item differs from the original selected step). ``new_claim``
    is the acquired claim row or ``None`` when no candidate could be claimed.
    """
    new_claim: Optional[Dict[str, Any]] = None
    if schedule.selected_step is None:
        return schedule, new_claim

    project_label = _canonical_project_label(conn, project_scope)
    skip_memory_at_offer = read_chain_skip_memory(conn, session_id)
    skipped_in_memory = {
        normalize_claim_item_id(str(entry.get("item_id")))
        for entry in skip_memory_at_offer
        if entry.get("item_id")
    }

    _assignable_states = {"unclaimed", "claimed_by_stale"}
    candidates = [schedule.selected_step] + [
        s
        for s in schedule.ranked_steps
        if s.item_id != schedule.selected_step.item_id
        and s.claim_state.value in _assignable_states
    ]
    candidates = [
        c
        for c in candidates
        if normalize_claim_item_id(str(c.item_id)) not in skipped_in_memory
    ]
    max_attempts = min(3, len(candidates))

    for attempt_idx in range(max_attempts):
        candidate = candidates[attempt_idx]
        valid, current_status = revalidate_candidate_status(
            conn,
            item_id=candidate.item_id,
            expected_status=candidate.status,
        )
        if not valid:
            record_offer_skip(
                conn,
                session_id=session_id,
                item_id=candidate.item_id,
                skip_reason="stale_lifecycle",
                chain_step=step,
                project=project_label,
                expected_status=candidate.status,
                current_status=current_status,
                expected_next_step=candidate.next_step.value,
            )
            continue

        if candidate.claim_state.value == "claimed_by_stale":
            reclaimed = reclaim_stale_item_claims(conn, candidate.item_id)
            if reclaimed:
                logger.info(
                    "Reclaimed %d stale claim(s) on %s before offer",
                    reclaimed,
                    candidate.item_id,
                )
        try:
            new_claim = claim_work(
                conn,
                session_id=session_id,
                item_id=candidate.item_id,
                claim_type="exclusive",
            )
            post_valid, post_current = revalidate_candidate_status(
                conn, item_id=candidate.item_id, expected_status=candidate.status
            )
            if not post_valid:
                released_claim_id = (new_claim or {}).get("id")
                release_item_claim_for_execution(
                    conn, session_id, str(candidate.item_id), "offer-override"
                )
                record_offer_skip(
                    conn,
                    session_id=session_id,
                    item_id=candidate.item_id,
                    skip_reason=SKIP_REASON_STALE_LIFECYCLE_POST_CLAIM,
                    chain_step=step,
                    project=project_label,
                    expected_status=candidate.status,
                    current_status=post_current,
                    expected_next_step=candidate.next_step.value,
                    holder_context={"claim_id": released_claim_id},
                )
                new_claim = None
                continue
            if candidate.item_id != schedule.selected_step.item_id:
                schedule, pinned = recompute_and_pin_for_claim(
                    conn,
                    session_id=session_id,
                    project_scope=project_scope,
                    wip_cap=wip_cap,
                    workspace=workspace,
                    execution_lane=authoritative_lane,
                    supported_paths=supported_paths,
                    lane_allowed_paths=lane_allowed_paths,
                    candidate=candidate,
                    new_claim=new_claim,
                    chain_step=step,
                    post_current=post_current,
                )
                if not pinned:
                    new_claim = None
                    continue
            break
        except SessionError as exc:
            if exc.code in ("ALREADY_CLAIMED", "DUPLICATE_CLAIM"):
                logger.info(
                    "Claim race on %s (attempt %d): %s",
                    candidate.item_id,
                    attempt_idx + 1,
                    exc.message,
                )
                holder = holder_session_for_item(conn, candidate.item_id)
                record_offer_skip(
                    conn,
                    session_id=session_id,
                    item_id=candidate.item_id,
                    skip_reason="live_claim_conflict",
                    chain_step=step,
                    project=project_label,
                    expected_status=candidate.status,
                    current_status=current_status,
                    expected_next_step=candidate.next_step.value,
                    holder_context=holder,
                )
                new_claim = None
                continue
            raise

    return schedule, new_claim


__all__ = ["acquire_claim_from_candidates"]
