"""Decide whether a repeated create names the launch already on file.

An idempotency key is a promise that retrying costs nothing. That only holds
if the replay is compared against what the caller asked for, so this compares
the stored request fields -- never anything the control plane derived from
them. Placement and the machine-resolved model can both move between a create
and its retry without making the retry a different request.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.session_launch_store import instruction_message, sha256_text
from yoke_core.domain.session_launch_types import (
    LaunchCreateOutcome,
    LaunchPreview,
    LaunchRecord,
    LaunchRequest,
    SessionLaunchError,
)


def same_request(conn: Any, launch: LaunchRecord, request: LaunchRequest) -> bool:
    """Compare a stored launch against the request that would create it."""
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


def deduplicated_outcome(
    conn: Any,
    *,
    existing: LaunchRecord,
    request: LaunchRequest,
    preview: LaunchPreview,
) -> LaunchCreateOutcome:
    """Return the launch on file, or refuse a key reused for other work."""
    if not same_request(conn, existing, request):
        raise SessionLaunchError(
            "idempotency_conflict",
            "idempotency key already names a different launch request",
        )
    return LaunchCreateOutcome(existing, preview, True)


__all__ = ["deduplicated_outcome", "same_request"]
