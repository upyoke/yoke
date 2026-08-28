"""Bounded observation of Claude Remote Control attachment state."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat
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
from yoke_harness.hooks.identity_runtime import is_claude


_MAX_JOB_STATE_BYTES = 64 * 1024


def _job_state_path(session_id: str) -> Path | None:
    try:
        UUID(session_id)
    except (TypeError, ValueError, AttributeError):
        return None
    configured = os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
    root = Path(configured).expanduser() if configured else Path.home() / ".claude"
    return root / "jobs" / session_id[:8] / "state.json"


def _bounded_state(path: Path) -> dict[str, Any] | None:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags)
        details = os.fstat(descriptor)
        if not stat.S_ISREG(details.st_mode) or details.st_size > _MAX_JOB_STATE_BYTES:
            return None
        raw = os.read(descriptor, _MAX_JOB_STATE_BYTES + 1)
        if len(raw) > _MAX_JOB_STATE_BYTES:
            return None
        decoded = json.loads(raw.decode("utf-8"))
        return decoded if isinstance(decoded, dict) else None
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    finally:
        if descriptor is not None:
            os.close(descriptor)


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
    path = _job_state_path(session_id)
    state = _bounded_state(path) if path is not None else None
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
