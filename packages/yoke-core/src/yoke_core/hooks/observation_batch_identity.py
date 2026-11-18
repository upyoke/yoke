"""Heal a batched observation's session identity without reviving the past."""

from __future__ import annotations

import json
from typing import Any


def refresh_session_identity(
    conn: Any,
    *,
    payload: dict[str, Any],
    context: Any,
    actor_id: int,
    observed_at: Any = None,
) -> None:
    """Apply wire identity through the ordinary active-session healing path.

    The batch's recorded instant keeps a retained observation from before a
    session's end from reviving it.
    """
    from yoke_core.hooks.registration import ensure_registered_from_hook

    transcript = payload.get("transcript_path")
    ensure_registered_from_hook(
        conn,
        json.dumps(payload),
        context.session_id or "",
        transcript_path=transcript if isinstance(transcript, str) else "",
        record_anchor=False,
        executor_hint=context.executor_family or "",
        register_in_process=True,
        actor_id=actor_id,
        project_id=payload.get("project_id"),
        observed_at=observed_at,
    )


__all__ = ["refresh_session_identity"]
