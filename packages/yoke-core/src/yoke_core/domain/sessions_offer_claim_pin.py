"""Post-claim schedule pinning for ``session_offer_with_ownership``.

Extracted sibling of :mod:`yoke_core.domain.sessions_offer`. The parent
file sits AT the 350-line cap; this module owns the helpers needed by
the post-claim recompute branch.

Why it exists: when ``session_offer_with_ownership`` walks its candidate
set and acquires a fallback claim (because the originally-selected
step lost a live-claim race or revalidation skip), it recomputes the
global schedule to refresh ``lane_filtered_*`` and the claim-state
projection. After the recompute, the schedule's ``selected_step`` may
point at a *different* item than the one we just claimed — another
session may have released a higher-ranked item between
``claim_work`` and the recompute. If the parent flow trusted that
recomputed ``selected_step``, the downstream frontier would name an
item we do not own and the charge-invariant guard would refuse to emit.

The fix is to pin ``schedule.selected_step`` to the ranked step
matching the actually-claimed ``item_id``. When the acquired item is
absent from the recomputed ``ranked_steps`` (rare — transient
lifecycle / lane state moved it out), the caller releases the claim
and continues the candidate walk rather than emitting a mismatched
directive.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .scheduler import compute_schedule
from .scheduler_skip_reasons import SKIP_REASON_STALE_LIFECYCLE_POST_CLAIM
from .sessions_lifecycle_release import release_item_claim_for_execution
from .sessions_offer_revalidation import record_offer_skip
from .sessions_queries import _filter_schedule_for_offer


def pin_schedule_to_acquired_item(
    schedule: Any,
    *,
    acquired_item_id: Any,
) -> bool:
    """Pin ``schedule.selected_step`` to the ranked step matching the claim.

    Returns ``True`` when a ranked step with ``item_id == acquired_item_id``
    was found and ``schedule.selected_step`` was updated in place.

    Returns ``False`` when the recomputed ``ranked_steps`` does NOT
    contain the acquired item. The comparison normalizes both sides to
    ``str`` so callers that pass either the raw ``new_claim["item_id"]``
    (which may be an int) or ``candidate.item_id`` (the ``YOK-N``
    string) work uniformly.
    """
    if schedule is None:
        return False
    ranked = getattr(schedule, "ranked_steps", None) or []
    if not ranked:
        return False
    target = str(acquired_item_id)
    for step in ranked:
        if str(step.item_id) == target:
            schedule.selected_step = step
            return True
    return False


def release_acquired_on_pin_miss(
    conn: Any,
    *,
    session_id: str,
    new_claim: Optional[Dict[str, Any]],
    candidate: Any,
    chain_step: int,
    project_label: str,
    post_current: Optional[str],
) -> None:
    """Release a claim acquired for an item the recomputed schedule no longer ranks.

    Mirrors the pre-existing post-claim revalidation cleanup: release
    the claim with intent ``offer-post-claim-pin-missing`` and record
    the skip so the same item is not re-offered later in the chain.
    """
    released_claim_id = (new_claim or {}).get("id")
    release_item_claim_for_execution(
        conn, session_id, str(candidate.item_id),
        "offer-post-claim-pin-missing",
    )
    record_offer_skip(
        conn,
        session_id=session_id,
        item_id=candidate.item_id,
        skip_reason=SKIP_REASON_STALE_LIFECYCLE_POST_CLAIM,
        chain_step=chain_step,
        project=project_label,
        expected_status=candidate.status,
        current_status=post_current,
        expected_next_step=candidate.next_step.value,
        holder_context={"claim_id": released_claim_id},
    )


def recompute_and_pin_for_claim(
    conn: Any,
    *,
    session_id: str,
    project_scope: List[int],
    wip_cap: int,
    execution_lane: str,
    supported_paths: Optional[List[str]],
    lane_allowed_paths: Optional[Dict[str, List[str]]],
    candidate: Any,
    new_claim: Optional[Dict[str, Any]],
    chain_step: int,
    post_current: Optional[str],
) -> Tuple[Any, bool]:
    """Recompute the schedule, pin selected_step to the acquired claim.

    Returns ``(schedule, pinned)``. When ``pinned`` is ``True``, the
    caller may proceed with the acquired claim. When ``pinned`` is
    ``False``, the claim has already been released and the skip
    recorded — the caller must clear its local ``new_claim`` and
    continue the candidate walk.
    """
    from .frontier_compute import _canonical_project_label

    schedule = compute_schedule(
        conn, project_scope=project_scope, wip_cap=wip_cap,
        session_id=session_id,
    )
    schedule = _filter_schedule_for_offer(
        schedule, execution_lane=execution_lane,
        supported_paths=supported_paths,
        lane_allowed_paths=lane_allowed_paths,
    )
    if pin_schedule_to_acquired_item(
        schedule, acquired_item_id=candidate.item_id,
    ):
        return schedule, True
    release_acquired_on_pin_miss(
        conn, session_id=session_id, new_claim=new_claim,
        candidate=candidate, chain_step=chain_step,
        project_label=_canonical_project_label(conn, project_scope),
        post_current=post_current,
    )
    return schedule, False


__all__ = [
    "pin_schedule_to_acquired_item",
    "release_acquired_on_pin_miss",
    "recompute_and_pin_for_claim",
]
