"""Record the level an item-bound launch starts at as the item's level.

A worker launched at one level and handed a stage whose effective level
differs is told to stop and relaunch (``level_change``). Launching an item at
``--level L`` therefore pins the item's ``level`` posture to ``L`` for every
stage, in the same transaction that creates the launch, so the worker is not
handed back at its first stage edge. The launching seat's own authority writes
it: ``create_launch`` has already required launch-operator authority, and no
claim is acquired or released. A launch that fails after the pin rolls it back.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.item_posture_amend import amend_item_posture
from yoke_core.domain.item_posture_amend_guards import ItemPostureAmendError
from yoke_core.domain.item_ref_resolution import resolve_item_ref_or_none
from yoke_core.domain.refusal_recovery import compose_refusal
from yoke_core.domain.session_launch_types import (
    LaunchAuthorization,
    LaunchRequest,
    SessionLaunchError,
)

DEFAULT_LEVEL_REASON = "launch-time level"


def pin_item_level(
    conn: Any, *, request: LaunchRequest, auth: LaunchAuthorization
) -> dict[str, Any] | None:
    """Pin the item to the launch level for all stages; ``None`` when not asked.

    Only an item-bound launch with an explicit level carries a reason, so a
    stage-level default, an exact selection, and an itemless launch all return
    ``None`` without touching posture.
    """
    if not (request.item and request.level and request.level_reason):
        return None
    item_id = resolve_item_ref_or_none(conn, request.item, project=request.project_id)
    if item_id is None:
        return None
    try:
        amended = amend_item_posture(
            conn,
            item_id=item_id,
            key="level",
            value={
                "min": request.level,
                "max": request.level,
                "reason": request.level_reason,
            },
            reason=f"launch create --level {request.level}",
            actor_id=auth.actor_id,
            session_id=auth.session_id or "",
            commit=False,
        )
    except ItemPostureAmendError as exc:
        raise SessionLaunchError(
            "item_level_not_recordable",
            compose_refusal(
                f"{request.item} cannot record {request.level} as its level, so "
                "the launch did not start",
                evaluated=str(exc),
                recovery=(
                    "launch without --level to use the item's effective stage "
                    "level, or correct the cause above and retry the same command"
                ),
            ),
        ) from exc
    return {
        "level": request.level,
        "reason": request.level_reason,
        "changed": bool(amended["changed"]),
        "previous": amended["before"].get("level"),
    }


__all__ = ["DEFAULT_LEVEL_REASON", "pin_item_level"]
