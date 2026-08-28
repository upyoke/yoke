"""How one session relates to the item its card is focused on.

An item belongs in a session's work position only when that session is
doing it. Three relationships put it there — the session holds the item's
work claim, the session runs a worktree lane on another session's item,
or the session filed the item and nobody has picked it up — and one fact
keeps it out: another live session holds the claim, which makes the item
that session's work however this one came to be attributed to it.

Split from :mod:`sessions_list_read` (authored-file line cap), which
composes the result straight into each roster row.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping, Optional


def focus_attribution(
    session_id: str,
    current_item_display: Optional[str],
    current_item_id: Any,
    *,
    claims: Iterable[Mapping[str, Any]],
    roles: Iterable[Mapping[str, Any]],
    item_holders: Mapping[int, str],
) -> Dict[str, Any]:
    """Name this session's relationship to its focused item.

    ``item_holders`` maps an item to the live session holding its work
    claim (see
    :func:`yoke_core.domain.sessions_holdings_read.live_item_claim_holders`);
    a holder that is not this session becomes
    ``current_item_holder_session_id`` so readers can tell attribution
    from work.
    """
    item_claims = [
        claim
        for claim in claims
        if claim.get("target_kind") == "item"
        and claim.get("target") == current_item_display
    ]
    owns_current_item = bool(item_claims)
    item_num = int(current_item_id) if current_item_id is not None else None
    held_roles = [claim for claim in roles if claim.get("item_id") == item_num]
    task_roles = [
        claim.get("lane_role")
        for claim in held_roles
        if claim.get("target_kind") == "epic_task" and claim.get("lane_role")
    ]
    item_roles = [
        claim.get("lane_role")
        for claim in held_roles
        if claim.get("target_kind") == "item" and claim.get("lane_role")
    ]
    # The lane role of the session's own claim on its current item, or
    # "item" when it holds that claim without a lane. A session whose
    # focus is mere attribution — an item it filed or updated but holds
    # no claim on — has no role at all, so readers never dress
    # attribution as a worktree lane.
    work_role = next(iter(task_roles or item_roles), None)
    if not work_role and owns_current_item:
        work_role = "item"
    holder = item_holders.get(item_num) if item_num is not None else None
    return {
        "work_role": work_role,
        "owns_current_item": owns_current_item,
        "claim_started_at": (
            item_claims[0].get("claimed_at") if item_claims else None
        ),
        "current_item_holder_session_id": (
            holder if holder and holder != session_id else None
        ),
    }


__all__ = ["focus_attribution"]
