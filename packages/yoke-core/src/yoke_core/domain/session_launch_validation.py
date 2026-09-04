"""Payload validation for persisted session launch requests."""

from __future__ import annotations

from dataclasses import replace

from yoke_contracts.executor_labels import KNOWN_SURFACE_LABELS
from yoke_contracts.session_control.model_selection import (
    LaunchModelSelection,
    LaunchModelSelectionError,
    validate_launch_model_selection,
)
from yoke_contracts.session_control.models import LaunchPreviewRequest
from yoke_core.domain.session_launch_types import (
    LaunchRequest,
    MAX_LAUNCH_DEADLINE_SECONDS,
    SessionLaunchError,
)
from yoke_core.domain.session_launch_assignment import MAX_SESSION_NAME_LENGTH
from yoke_contracts.session_control.presentation import CLAUDE_LOCAL_PRESENTATION


def validate_launch_request(
    request: LaunchRequest, *, max_body_bytes: int
) -> LaunchRequest:
    if not request.executor_surface.strip():
        raise SessionLaunchError("payload_invalid", "executor surface is required")
    if request.executor_surface not in KNOWN_SURFACE_LABELS:
        raise SessionLaunchError("unsupported_surface", "executor surface is unknown")
    selection = validate_model_selection(
        request.executor_surface,
        model=request.model,
        reasoning_effort=request.reasoning_effort,
        context_window_tokens=request.context_window_tokens,
    )
    if not request.instructions.strip():
        raise SessionLaunchError("payload_invalid", "instructions must be non-empty")
    if len(request.instructions.encode("utf-8")) > max_body_bytes:
        raise SessionLaunchError("body_too_large", "instructions exceed the body limit")
    if not request.idempotency_key.strip():
        raise SessionLaunchError("payload_invalid", "idempotency key is required")
    if request.session_name is not None and (
        not request.session_name.strip()
        or len(request.session_name) > MAX_SESSION_NAME_LENGTH
    ):
        raise SessionLaunchError(
            "session_name_invalid",
            f"session name must be 1-{MAX_SESSION_NAME_LENGTH} characters",
        )
    if (
        request.executor_surface.startswith("claude-")
        and request.presentation != CLAUDE_LOCAL_PRESENTATION
    ):
        raise SessionLaunchError(
            "presentation_unsupported",
            "Claude launches require local presentation; omit --presentation "
            "or pass --presentation local",
        )
    if not 60 <= request.deadline_seconds <= MAX_LAUNCH_DEADLINE_SECONDS:
        raise SessionLaunchError(
            "deadline_invalid",
            f"deadline must be between 60 and {MAX_LAUNCH_DEADLINE_SECONDS} seconds",
        )
    return replace(
        request,
        model=selection.model,
        reasoning_effort=selection.reasoning_effort,
        context_window_tokens=selection.context_window_tokens,
    )


def validate_model_selection(
    surface: str,
    *,
    model: str | None,
    reasoning_effort: str | None,
    context_window_tokens: int | None,
) -> LaunchModelSelection:
    """Translate the shared harness-knob contract to a domain refusal."""
    try:
        return validate_launch_model_selection(
            surface,
            LaunchModelSelection(model, reasoning_effort, context_window_tokens),
        )
    except LaunchModelSelectionError as exc:
        raise SessionLaunchError(exc.code, str(exc)) from exc


def validate_preview_model_selection(
    surface: str, request: LaunchPreviewRequest
) -> LaunchModelSelection:
    return validate_model_selection(
        surface,
        model=request.model,
        reasoning_effort=request.reasoning_effort,
        context_window_tokens=request.context_window_tokens,
    )


def preview_model_selection_payload(
    selection: LaunchModelSelection,
) -> dict[str, object]:
    return {
        "requested_model": selection.model,
        "requested_reasoning_effort": selection.reasoning_effort,
        "requested_context_window_tokens": selection.context_window_tokens,
    }


__all__ = [
    "preview_model_selection_payload",
    "validate_launch_request",
    "validate_model_selection",
    "validate_preview_model_selection",
]
