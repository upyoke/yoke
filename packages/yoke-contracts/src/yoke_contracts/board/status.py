"""Status → board-bucket mapping — pure, client-tier.

Maps an item's lifecycle status (plus frozen/blocked flags, item type, and
active-run state) to its board display bucket. Hosted with the board render in
yoke_contracts so it ships everywhere; ``yoke_core.domain.board``
re-exports these for its existing callers.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from yoke_contracts.item_flags import is_blocked, is_frozen

# The special "frozen" bucket — excluded from normal board display.
FROZEN_BUCKET = "frozen"
# The "blocked" bucket — blocked-flagged items (legacy ``status='blocked'`` too).
BLOCKED_BUCKET = "blocked"
# The "unknown" bucket — items with unrecognized statuses.
UNKNOWN_BUCKET = "unknown"

# Direct status-to-bucket map for items (no task context, no active-run check).
_STATUS_TO_BUCKET: Dict[str, str] = {
    # Terminal / exceptional statuses
    "done": "done",
    "cancelled": "done",
    "blocked": "blocked",
    "stopped": "blocked",
    "failed": "blocked",
    # Current lifecycle statuses → board buckets
    "release": "release",
    "implemented": "implemented",
    "implementing": "implementing",
    "reviewing-implementation": "reviewing",
    "reviewed-implementation": "reviewing",
    "polishing-implementation": "reviewing",
    "refined-idea": "refined",
    "planned": "refined",
    "refining-idea": "planning",
    "planning": "planning",
    "plan-drafted": "planning",
    "refining-plan": "planning",
    "idea": "idea",
}

# Type-aware overrides: (item_type, status) -> bucket, applied when item_type is
# provided, for shared tokens with different semantics across lifecycle families.
_TYPE_AWARE_OVERRIDES: Dict[tuple, str] = {
    ("epic", "refined-idea"): "planning",
    ("epic", "reviewing-implementation"): "implementing",
}


def status_to_board_bucket(
    status: str,
    frozen_value: Any = None,
    has_active_run: bool = False,
    item_type: Optional[str] = None,
    blocked_value: Any = None,
) -> str:
    """Map an item's status to its board display bucket.

    Rule order: 1) done/cancelled -> done (any flag); 2) frozen -> frozen;
    2b) blocked-flag -> blocked (after frozen, so frozen+blocked renders frozen);
    3) implemented + active-run -> release; 4) type-aware overrides; 5) the
    standard status mapping (``UNKNOWN_BUCKET`` for unrecognized statuses).
    """
    if status in ("done", "cancelled"):
        return "done"
    if is_frozen(frozen_value):
        return FROZEN_BUCKET
    if is_blocked(blocked_value):
        return BLOCKED_BUCKET
    if status == "implemented" and has_active_run:
        return "release"
    if item_type is not None:
        override = _TYPE_AWARE_OVERRIDES.get((item_type, status))
        if override is not None:
            return override
    return _STATUS_TO_BUCKET.get(status, UNKNOWN_BUCKET)
