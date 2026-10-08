"""Compose the launch preview a caller reads before it creates a launch.

A level preview places the level the way a create would and reports the
option and machine it chose with the placement evidence; an explicit preview
places the exact selection the caller named. Both report the selection the
launch would carry and where each knob came from.
"""

from __future__ import annotations

from typing import Any

from yoke_contracts.session_control.models import LaunchPreviewRequest
from yoke_core.domain.session_launch_eligibility import derive_launch_eligibility
from yoke_core.domain.session_launch_level_selection import (
    level_source,
    preview_level_launch,
)
from yoke_core.domain.session_launch_machine_models import resolve_machine_selection
from yoke_core.domain.session_launch_store import utc_now
from yoke_core.domain.session_launch_surface_selection import preview_launch
from yoke_core.domain.session_launch_types import (
    LaunchAuthorization,
    LaunchRequest,
    ensure_operator,
)
from yoke_core.domain.session_launch_validation import (
    preview_model_selection_payload,
    validate_preview_model_selection,
)


def level_preview_payload(
    conn: Any, *, auth: LaunchAuthorization, project_id: int, level: str
) -> dict[str, Any]:
    """Preview where a launch at ``level`` would go, and why."""
    ensure_operator(auth)
    placed, preview = preview_level_launch(
        conn,
        auth=auth,
        request=LaunchRequest(
            project_id=project_id,
            executor_surface="",
            instructions="",
            idempotency_key="",
            level=level,
        ),
        now=utc_now(),
        eligibility=derive_launch_eligibility,
    )
    payload = preview.to_dict()
    payload["requested_level"] = placed.level
    relay = preview.selected_relay
    if relay is not None:
        payload.update(
            resolve_machine_selection(
                conn,
                requested_model=placed.model,
                requested_reasoning_effort=placed.reasoning_effort,
                requested_context_window_tokens=placed.context_window_tokens,
                machine_id=relay.machine_id,
                surface=relay.surface,
                explicit_source=level_source(str(placed.level)),
            ).to_dict()
        )
    return payload


def explicit_preview_payload(
    conn: Any,
    *,
    auth: LaunchAuthorization,
    project_id: int,
    parsed: LaunchPreviewRequest,
    surface_fallback_enabled: bool,
) -> dict[str, Any]:
    """Preview an exact selection, launched as the caller named it."""
    surface = str(parsed.executor_surface)
    selection = validate_preview_model_selection(surface, parsed)
    preview = preview_launch(
        conn,
        auth=auth,
        project_id=project_id,
        surface=surface,
        machine_id=parsed.machine_id,
        allow_surface_fallback=parsed.allow_surface_fallback,
        surface_fallback_enabled=surface_fallback_enabled,
        model=parsed.model,
    )
    if preview.selected_surface:
        selection = validate_preview_model_selection(preview.selected_surface, parsed)
    payload = preview.to_dict()
    payload.update(preview_model_selection_payload(selection))
    relay = preview.selected_relay
    payload.update(
        resolve_machine_selection(
            conn,
            requested_model=parsed.model,
            requested_reasoning_effort=parsed.reasoning_effort,
            requested_context_window_tokens=parsed.context_window_tokens,
            machine_id=relay.machine_id if relay else None,
            surface=relay.surface if relay else surface,
        ).to_dict()
    )
    return payload


__all__ = ["explicit_preview_payload", "level_preview_payload"]
