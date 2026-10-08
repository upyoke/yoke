"""Turn a level launch into the exact launch it will run as.

Level placement chooses an option and a machine; everything after that is
the ordinary launch path, so a level launch is relay-selected, validated,
stored, and verified exactly like a launch that named its own selection.
This module is the seam: it places the level, fills the chosen option into
the request, previews it pinned to the chosen machine, and stamps the
preview with the placement evidence.
"""

from __future__ import annotations

from datetime import datetime

from dataclasses import replace
from typing import Any

from yoke_core.domain import session_relay_managed_presentation as presentation
from yoke_core.domain.session_launch_level_placement import (
    LEVEL_NO_CAPACITY,
    LevelPlacement,
    place_level,
)
from yoke_core.domain.session_launch_surface_selection import preview_launch
from yoke_core.domain.session_launch_types import (
    LaunchAuthorization,
    LaunchEligibilityPort,
    LaunchPreview,
    LaunchRequest,
)


def level_source(level: str) -> str:
    """How a level launch's knobs are attributed in its selection sources."""
    return f"level {level} option"


def _refused(request: LaunchRequest, placement: LevelPlacement) -> LaunchPreview:
    return LaunchPreview(
        outcome=LEVEL_NO_CAPACITY,
        requested_surface=request.executor_surface,
        eligible_relays=(),
        placement_reason=placement.reason,
        level_placement=placement.to_dict(),
    )


def preview_level_launch(
    conn: Any,
    *,
    auth: LaunchAuthorization,
    request: LaunchRequest,
    now: datetime | str,
    eligibility: LaunchEligibilityPort,
) -> tuple[LaunchRequest, LaunchPreview]:
    """Place ``request.level`` and preview the launch it chose.

    Returns the request filled with the chosen option, and a preview whose
    placement line and evidence come from the level. When no option has
    capacity the request comes back unchanged beside a non-launchable
    ``level_no_capacity`` preview naming every blocked option.
    """
    placement = place_level(
        conn,
        auth=auth,
        project_id=request.project_id,
        level=str(request.level),
        machine_id=request.machine_id,
        now=now,
        eligibility=eligibility,
    )
    chosen = placement.chosen
    if chosen is None:
        return request, _refused(request, placement)
    placed = presentation.normalize_launch_presentation(
        replace(
            request,
            level=placement.level,
            executor_surface=chosen.surface,
            model=chosen.model,
            reasoning_effort=chosen.reasoning_effort,
            context_window_tokens=chosen.context_window_tokens,
        )
    )
    preview = preview_launch(
        conn,
        auth=auth,
        project_id=request.project_id,
        surface=chosen.surface,
        machine_id=chosen.machine_id,
        now=now,
        model=chosen.model,
        eligibility=eligibility,
    )
    return placed, replace(
        preview,
        placement_reason=(
            f"level {placement.level}: {placement.reason}"
            if preview.launchable
            else preview.placement_reason
        ),
        level_placement=placement.to_dict(),
    )


__all__ = ["level_source", "preview_level_launch"]
