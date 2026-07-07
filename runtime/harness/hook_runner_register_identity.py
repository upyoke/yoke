"""Identity-upgrade probes for hook-runner session registration."""

from __future__ import annotations

import json
from typing import Any


def _placeholder_model_can_upgrade(
    conn: Any, payload_json: str, session_id: str,
) -> bool:
    """True when wire model can heal a placeholder stored row."""
    try:
        if not payload_json:
            return False
        payload = json.loads(payload_json)
        if not isinstance(payload, dict):
            return False
        from runtime.harness.hook_helpers import _is_placeholder_model

        wire_model = payload.get("model", "")
        if (
            not isinstance(wire_model, str)
            or not wire_model
            or _is_placeholder_model(wire_model)
        ):
            return False
        from yoke_core.domain import db_backend

        p = "%s" if db_backend.connection_is_postgres(conn) else "?"
        row = conn.execute(
            f"SELECT model FROM harness_sessions WHERE session_id = {p}",
            (session_id,),
        ).fetchone()
        if row is None:
            return False
        stored = row.get("model") if hasattr(row, "get") else row[0]
        return _is_placeholder_model(stored or "")
    except Exception:  # noqa: BLE001 - probe must never break dispatch
        return False


def placeholder_identity_can_upgrade(
    conn: Any, payload_json: str, session_id: str,
) -> bool:
    """True when wire identity can heal a placeholder stored row."""
    if _placeholder_model_can_upgrade(conn, payload_json, session_id):
        return True
    try:
        if not payload_json:
            return False
        payload = json.loads(payload_json)
        if not isinstance(payload, dict):
            return False
        wire_lane = payload.get("execution_lane", "")
        if not isinstance(wire_lane, str):
            return False
        from yoke_core.domain import db_backend
        from yoke_core.domain.sessions_lifecycle_identity import lane_should_upgrade

        p = "%s" if db_backend.connection_is_postgres(conn) else "?"
        row = conn.execute(
            f"SELECT execution_lane FROM harness_sessions WHERE session_id = {p}",
            (session_id,),
        ).fetchone()
        if row is None:
            return False
        stored = row.get("execution_lane") if hasattr(row, "get") else row[0]
        return lane_should_upgrade(stored or "", wire_lane.strip())
    except Exception:  # noqa: BLE001 - probe must never break dispatch
        return False


__all__ = ["placeholder_identity_can_upgrade"]
