"""Persistence and idempotency helpers for session launch requests."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.session_launch_machine_models import resolve_machine_model
from yoke_core.domain.session_launch_origin import derived_launch_origin
from yoke_core.domain.session_launch_store import (
    instruction_message,
    marker,
    sha256_text,
)
from yoke_core.domain.session_launch_types import (
    LaunchAuthorization,
    LaunchPreview,
    LaunchRecord,
    LaunchRequest,
)


def same_launch_request(
    conn: Any,
    launch: LaunchRecord,
    request: LaunchRequest,
) -> bool:
    body, body_hash, _ = instruction_message(conn, launch.message_id)
    return all(
        (
            launch.project_id == request.project_id,
            launch.requested_surface == request.executor_surface,
            launch.requested_machine_id == request.machine_id,
            launch.requested_model == request.model,
            launch.requested_reasoning_effort == request.reasoning_effort,
            launch.requested_context_window_tokens == request.context_window_tokens,
            launch.presentation_preference == request.presentation,
            launch.session_name == request.session_name,
            launch.allow_surface_fallback == request.allow_surface_fallback,
            body_hash == sha256_text(request.instructions),
            body == request.instructions,
        )
    )


def insert_launch_request(
    conn: Any,
    *,
    launch_id: str,
    message_id: str,
    auth: LaunchAuthorization,
    request: LaunchRequest,
    preview: LaunchPreview,
    created_at: str,
    deadline_at: str,
) -> bool:
    relay = preview.selected_relay
    assert relay is not None
    p = marker(conn)
    columns = (
        "launch_id, requester_actor_id, requester_session_id, project_id, "
        "requested_surface, selected_surface, requested_machine_id, requested_model, "
        "requested_reasoning_effort, requested_context_window_tokens, "
        "presentation_preference, session_name, allow_surface_fallback, message_id, "
        "idempotency_key, state, assigned_relay_id, assigned_machine_id, "
        "deadline_at, created_at, assigned_at, origin, placement_reason, "
        "resolved_model"
    )
    values = (
        launch_id,
        auth.actor_id,
        auth.session_id,
        request.project_id,
        request.executor_surface,
        relay.surface,
        request.machine_id,
        request.model,
        request.reasoning_effort,
        request.context_window_tokens,
        request.presentation,
        request.session_name,
        int(request.allow_surface_fallback),
        message_id,
        request.idempotency_key,
        "assigned",
        relay.relay_id,
        relay.machine_id,
        deadline_at,
        created_at,
        created_at,
        derived_launch_origin(
            conn,
            session_id=auth.session_id,
            project_id=request.project_id,
        ),
        preview.placement_reason,
        resolve_machine_model(
            conn,
            requested_model=request.model,
            machine_id=relay.machine_id,
            surface=relay.surface,
        ).model,
    )
    row = conn.execute(
        f"INSERT INTO session_launches ({columns}) "
        f"VALUES ({', '.join(p for _ in values)}) "
        "ON CONFLICT DO NOTHING RETURNING launch_id",
        values,
    ).fetchone()
    return row is not None


__all__ = ["insert_launch_request", "same_launch_request"]
