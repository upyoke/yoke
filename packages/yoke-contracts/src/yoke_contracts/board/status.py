"""Status → board-bucket mapping — pure, client-tier.

Maps an item's lifecycle stage (plus flags, its pinned workflow definition,
and active-run state) to its board display bucket. Hosted with the board render
in yoke_contracts so it ships everywhere; ``yoke_core.domain.board`` re-exports
these for its existing callers.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from yoke_contracts.item_flags import is_blocked, is_frozen

# The special "frozen" bucket — excluded from normal board display.
FROZEN_BUCKET = "frozen"
# The "blocked" bucket — blocked-flagged items (legacy ``status='blocked'`` too).
BLOCKED_BUCKET = "blocked"
# The "unknown" bucket — items with unrecognized statuses.
UNKNOWN_BUCKET = "unknown"
BOARD_BUCKET_ORDER = (
    "idea",
    "planning",
    "refined",
    "implementing",
    "blocked",
    "reviewing",
    "implemented",
    "release",
    "done",
)

# Compatibility mapping for context-free clients. Authoritative item reads pass
# the pinned definition and use ``_definition_bucket`` below.
_CONTEXT_FREE_STAGE_BUCKETS: dict[str, str] = {
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

# Private compatibility exports retained for the legacy domain re-export.
_STATUS_TO_BUCKET = _CONTEXT_FREE_STAGE_BUCKETS
_WORKFLOW_AWARE_OVERRIDES: dict[tuple[str, str], str] = {}


def _definition_bucket(
    status: str,
    definition: Mapping[str, Any],
) -> str:
    """Project a declared stage from skill segments and workflow policy."""
    stages = tuple(definition.get("stages") or ())
    stage_ids = tuple(str(stage.get("id")) for stage in stages)
    terminal_ids = {
        str(stage_id) for stage_id in definition.get("terminal_stage_ids") or ()
    }
    if status in terminal_ids:
        return "done"
    try:
        position = stage_ids.index(status)
    except ValueError:
        return UNKNOWN_BUCKET
    if position == 0:
        return "idea"

    for binding in definition.get("skill_bindings") or ():
        try:
            start = stage_ids.index(str(binding["from_stage_id"]))
            stop = stage_ids.index(str(binding["through_stage_id"]))
        except (KeyError, ValueError):
            continue
        if not start <= position < stop:
            continue

        skill_id = str(binding.get("skill_id") or "")
        if skill_id in {"refine", "shepherd"}:
            return "planning"
        if skill_id == "polish":
            return "reviewing"
        if skill_id == "usher":
            return "implemented" if position == start else "release"

        # Every other registered skill owns implementation. Its entry is
        # ready work, its interior is active work, and its final interior stage
        # is review. Task-graph workflows keep that integration close active
        # until their implementation skill reaches its handoff.
        if position == start:
            return "refined"
        policies = definition.get("policies") or {}
        if (
            position + 1 == stop
            and policies.get("generated_children") != "epic_tasks"
        ):
            return "reviewing"
        return "implementing"
    return UNKNOWN_BUCKET


def status_to_board_bucket(
    status: str,
    frozen_value: Any = None,
    has_active_run: bool = False,
    workflow_id: Optional[str] = None,
    blocked_value: Any = None,
    *,
    workflow_definition: Optional[Mapping[str, Any]] = None,
) -> str:
    """Map an item's status to its board display bucket.

    Rule order: 1) terminal/cancelled -> done (any flag); 2) frozen -> frozen;
    2b) blocked-flag -> blocked (after frozen, so frozen+blocked renders frozen);
    3) derive the stage bucket from the pinned definition; 4) upgrade an
    implemented item with an active delivery run to release.

    ``workflow_id`` remains a compatibility argument for client callers, but
    identity never changes lifecycle semantics.
    """
    del workflow_id
    terminal_ids = (
        {
            str(stage_id)
            for stage_id in workflow_definition.get("terminal_stage_ids") or ()
        }
        if workflow_definition is not None
        else set()
    )
    if status in terminal_ids or status in ("done", "cancelled"):
        return "done"
    if is_frozen(frozen_value):
        return FROZEN_BUCKET
    if is_blocked(blocked_value):
        return BLOCKED_BUCKET
    bucket = (
        _definition_bucket(status, workflow_definition)
        if workflow_definition is not None
        else _CONTEXT_FREE_STAGE_BUCKETS.get(status, UNKNOWN_BUCKET)
    )
    if bucket == "implemented" and has_active_run:
        return "release"
    return bucket
