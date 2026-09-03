"""Bounded observation of Claude Remote Control attachment state."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from yoke_contracts.session_control.presentation import (
    PRESENTATION_MODE_BIDIRECTIONAL,
    PRESENTATION_MODE_OUTBOUND_ONLY,
    PRESENTATION_SOURCE_CLAUDE_JOB_STATE,
    PRESENTATION_STATE_ATTACHED,
    PRESENTATION_STATE_NOT_ATTACHED,
    PRESENTATION_SURFACE_REMOTE_CONTROL,
)
from yoke_harness.claude_runtime_records import bounded_json_record, job_state_path
from yoke_harness.hooks.identity_runtime import is_claude


def _job_state(session_id: str) -> dict[str, Any] | None:
    try:
        UUID(session_id)
    except (TypeError, ValueError, AttributeError):
        return None
    # A background job is keyed by the leading eight characters of its session.
    return bounded_json_record(job_state_path(session_id[:8]))


def observe_claude_presentation(
    executor: str,
    payload: dict[str, Any],
) -> dict[str, str | None]:
    """Return safe bridge facts, or no opinion when state cannot be proven."""
    if not is_claude(executor):
        return {}
    session_id = payload.get("session_id")
    if not isinstance(session_id, str):
        return {}
    state = _job_state(session_id)
    if state is None or state.get("sessionId") != session_id:
        return {}
    bridge_id = state.get("bridgeSessionId")
    attached = isinstance(bridge_id, str) and bool(bridge_id.strip())
    mode = None
    if attached and state.get("bridgeOutboundOnly") is True:
        mode = PRESENTATION_MODE_OUTBOUND_ONLY
    elif attached and state.get("bridgeOutboundOnly") is False:
        mode = PRESENTATION_MODE_BIDIRECTIONAL
    return {
        "presentation_surface": (
            PRESENTATION_SURFACE_REMOTE_CONTROL if attached else None
        ),
        "presentation_state": (
            PRESENTATION_STATE_ATTACHED if attached else PRESENTATION_STATE_NOT_ATTACHED
        ),
        "presentation_mode": mode,
        "presentation_source": PRESENTATION_SOURCE_CLAUDE_JOB_STATE,
        "presentation_observed_at": datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
    }


__all__ = ["observe_claude_presentation"]
