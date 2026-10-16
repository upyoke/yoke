"""Session-identity resolution + source classification.

Owns the chain of session-id sources (env vars → payload → degraded
fallback) and the
``_classify_session_id_source`` helper that telemetry uses to record
where the resolved id came from. Re-exported via
``yoke_core.hooks.telemetry`` to preserve the public surface
that mock-patches against ``hook_runner.telemetry.X`` rely on.
"""

from __future__ import annotations

import json
import os
import time
from typing import Optional

from yoke_core.domain.session_ambient_identity import AMBIENT_ENV_VARS


def resolve_session_id_from_env_and_payload(
    payload_json: str = "",
) -> tuple[str, bool]:
    """Resolve session ID from env vars and optional hook payload JSON.

    Returns ``(session_id, has_canonical_id)`` where *has_canonical_id*
    indicates whether a stable (non-fallback) ID was found.
    """
    claude_sid = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    if claude_sid:
        return claude_sid, True

    if payload_json:
        try:
            data = json.loads(payload_json)
            payload_sid = data.get("session_id", "")
            if payload_sid:
                return payload_sid, True
        except (json.JSONDecodeError, TypeError):
            pass

    return f"fallback-{os.getpid()}-{int(time.time())}", False


def resolve_direct_session_id(payload_json: str = "") -> str:
    """Resolve only direct hook/session identity, never shared fallback lookup."""
    for env_var in AMBIENT_ENV_VARS:
        value = os.environ.get(env_var, "")
        if value:
            return value
    if payload_json:
        try:
            data = json.loads(payload_json)
            payload_sid = data.get("session_id", "")
            if payload_sid:
                return payload_sid
        except (json.JSONDecodeError, TypeError):
            pass
    return ""


def _classify_session_id_source(
    session_id: str,
    payload_json: str,
    env_snapshot: Optional[dict[str, str]] = None,
) -> str:
    """Identify where *session_id* was resolved from for telemetry."""
    if not session_id:
        return "missing"
    env = env_snapshot or os.environ
    for env_var in AMBIENT_ENV_VARS:
        if env.get(env_var, "") == session_id:
            return f"env:{env_var}"
    if payload_json:
        try:
            data = json.loads(payload_json)
            if isinstance(data, dict) and data.get("session_id") == session_id:
                return "payload"
        except (json.JSONDecodeError, TypeError):
            pass
    return "unknown"


__all__ = [
    "_classify_session_id_source",
    "resolve_direct_session_id",
    "resolve_session_id_from_env_and_payload",
]
