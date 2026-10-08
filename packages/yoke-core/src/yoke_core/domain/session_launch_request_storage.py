"""Persistence and idempotency helpers for session launch requests."""

from __future__ import annotations

from datetime import datetime
from yoke_contracts.timestamps import parse_instant
from yoke_core.domain.db_helpers import instant_parameter
from typing import Any

from yoke_core.domain import json_helper
from yoke_core.domain.session_launch_level_selection import level_source
from yoke_core.domain.session_launch_machine_models import (
    EXPLICIT_SOURCE,
    resolve_machine_selection,
)
from yoke_core.domain.session_launch_origin import derived_launch_origin
from yoke_core.domain.session_launch_store import marker
from yoke_core.domain.session_launch_types import (
    LaunchAuthorization,
    LaunchPreview,
    LaunchRecord,
    LaunchRequest,
)


def stored_level_placement(preview: LaunchPreview) -> str | None:
    """The preview's level placement evidence as stored JSON, if any."""
    if preview.level_placement is None:
        return None
    return json_helper.dumps_compact(preview.level_placement)


def retry_request(launch: LaunchRecord) -> LaunchRequest:
    """The ask a stored launch made, so a retry places it the same way.

    A level launch is placed again from its level, because the option and
    machine that fit at create time may not fit now; an explicit launch
    repeats its exact selection.
    """
    return LaunchRequest(
        project_id=launch.project_id,
        executor_surface="" if launch.requested_level else launch.requested_surface,
        instructions="",
        idempotency_key=str(launch.idempotency_key or ""),
        machine_id=launch.requested_machine_id,
        model=launch.requested_model,
        reasoning_effort=launch.requested_reasoning_effort,
        context_window_tokens=launch.requested_context_window_tokens,
        presentation=launch.presentation_preference,
        allow_surface_fallback=launch.allow_surface_fallback,
        level=launch.requested_level,
    )


def insert_launch_request(
    conn: Any,
    *,
    launch_id: str,
    message_id: str,
    auth: LaunchAuthorization,
    request: LaunchRequest,
    preview: LaunchPreview,
    created_at: datetime,
    deadline_at: datetime,
) -> bool:
    relay = preview.selected_relay
    assert relay is not None
    resolved = resolve_machine_selection(
        conn,
        requested_model=request.model,
        requested_reasoning_effort=request.reasoning_effort,
        requested_context_window_tokens=request.context_window_tokens,
        machine_id=relay.machine_id,
        surface=relay.surface,
        explicit_source=level_source(request.level)
        if request.level
        else EXPLICIT_SOURCE,
    )
    # A level launch asked for a level, not for the option placement chose:
    # the option is the resolved selection, and the ask stays the level.
    asked = (
        (None, None, None)
        if request.level
        else (
            request.model,
            request.reasoning_effort,
            request.context_window_tokens,
        )
    )
    p = marker(conn)
    columns = (
        "launch_id, requester_actor_id, requester_session_id, project_id, "
        "requested_surface, selected_surface, requested_machine_id, requested_model, "
        "requested_reasoning_effort, requested_context_window_tokens, "
        "presentation_preference, session_name, allow_surface_fallback, message_id, "
        "idempotency_key, state, assigned_relay_id, assigned_machine_id, "
        "deadline_at, created_at, assigned_at, origin, placement_reason, "
        "resolved_model, resolved_reasoning_effort, "
        "resolved_context_window_tokens, requested_level, level_placement"
    )
    values = (
        launch_id,
        auth.actor_id,
        auth.session_id,
        request.project_id,
        request.executor_surface,
        relay.surface,
        request.machine_id,
        *asked,
        request.presentation,
        request.session_name,
        int(request.allow_surface_fallback),
        message_id,
        request.idempotency_key,
        "assigned",
        relay.relay_id,
        relay.machine_id,
        instant_parameter(conn, parse_instant(deadline_at)),
        instant_parameter(conn, parse_instant(created_at)),
        instant_parameter(conn, parse_instant(created_at)),
        derived_launch_origin(
            conn,
            session_id=auth.session_id,
            project_id=request.project_id,
        ),
        preview.placement_reason,
        resolved.model,
        resolved.reasoning_effort,
        resolved.context_window_tokens,
        request.level,
        stored_level_placement(preview),
    )
    row = conn.execute(
        f"INSERT INTO session_launches ({columns}) "
        f"VALUES ({', '.join(p for _ in values)}) "
        "ON CONFLICT DO NOTHING RETURNING launch_id",
        values,
    ).fetchone()
    return row is not None


__all__ = ["insert_launch_request", "retry_request", "stored_level_placement"]
