"""Persist bounded, source-attested session presentation transitions."""

from __future__ import annotations

from datetime import datetime
import json
from typing import Any

from yoke_contracts.session_control.presentation import (
    PRESENTATION_MODES,
    PRESENTATION_SOURCE_CLAUDE_JOB_STATE,
    PRESENTATION_STATES,
    PRESENTATION_STATE_ATTACHED,
    PRESENTATION_STATE_NOT_ATTACHED,
    PRESENTATION_SURFACE_REMOTE_CONTROL,
)
from yoke_core.domain import db_backend


_FIELDS = (
    "presentation_surface",
    "presentation_state",
    "presentation_mode",
    "presentation_source",
    "presentation_observed_at",
)


def _marker(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _observation(payload_json: str) -> tuple[str | None, ...] | None:
    try:
        payload = json.loads(payload_json)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    surface = payload.get("presentation_surface")
    state = payload.get("presentation_state")
    mode = payload.get("presentation_mode")
    source = payload.get("presentation_source")
    observed_at = payload.get("presentation_observed_at")
    if state not in PRESENTATION_STATES or mode not in (*PRESENTATION_MODES, None):
        return None
    if source != PRESENTATION_SOURCE_CLAUDE_JOB_STATE:
        return None
    if not isinstance(observed_at, str):
        return None
    try:
        datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    if state == PRESENTATION_STATE_ATTACHED:
        if surface != PRESENTATION_SURFACE_REMOTE_CONTROL:
            return None
    elif state == PRESENTATION_STATE_NOT_ATTACHED and (
        surface is not None or mode is not None
    ):
        return None
    return surface, state, mode, source, observed_at


def record_session_presentation(
    conn: Any,
    *,
    session_id: str,
    payload_json: str,
) -> bool:
    """Store a newer material transition; repeated observations stay write-free."""
    observation = _observation(payload_json)
    if conn is None or not session_id or observation is None:
        return False
    marker = _marker(conn)
    row = conn.execute(
        "SELECT " + ",".join(_FIELDS) + " FROM harness_sessions "
        f"WHERE session_id={marker}",
        (session_id,),
    ).fetchone()
    if row is None:
        return False
    existing = tuple(row[index] for index in range(len(_FIELDS)))
    if existing[:4] == observation[:4]:
        return False
    if existing[4] is not None and str(observation[4]) < str(existing[4]):
        return False
    assignments = ",".join(f"{field}={marker}" for field in _FIELDS)
    conn.execute(
        f"UPDATE harness_sessions SET {assignments} WHERE session_id={marker}",
        (*observation, session_id),
    )
    conn.commit()
    return True


__all__ = ["record_session_presentation"]
