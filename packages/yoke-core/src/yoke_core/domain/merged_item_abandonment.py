"""Operator authority and durable resolution audit for merged abandonment."""

from __future__ import annotations

import json
from typing import Any

from yoke_contracts.timestamps import iso8601_now
from yoke_core.domain.session_steering_authority import require_operator_seat


def abandonment_audit(
    conn: Any, *, item: dict, session_id: str | None, reason: str
) -> str:
    """Require a covering operator seat; keep the audit in the close transaction."""
    require_operator_seat(
        conn,
        caller_session_id=session_id,
        project_id=int(item["project_id"]),
        action="Abandoning merged work",
    )
    from yoke_core.domain.project_identity import placeholder

    actor = conn.execute(
        f"SELECT actor_id FROM harness_sessions WHERE session_id={placeholder(conn)}",
        (session_id,),
    ).fetchone()
    return json.dumps(
        {
            "action": "abandon_merged",
            "session_id": session_id,
            "actor_id": actor[0] if actor else None,
            "from_status": item["status"],
            "merged_at": str(item["merged_at"]),
            "reason": reason,
            "recorded_at": iso8601_now(),
        },
        sort_keys=True,
    )
