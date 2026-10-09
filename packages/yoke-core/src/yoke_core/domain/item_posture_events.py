"""Transactional event projection for item posture amendments."""

from __future__ import annotations

from typing import Any, Optional

AMENDED_EVENT_NAME = "ItemWorkflowPostureAmended"


def emit_posture_amended(
    conn: Any,
    *,
    item_id: int,
    project: str,
    session_id: str,
    context: dict[str, Any],
) -> Optional[str]:
    from yoke_core.domain.events import emit_event

    envelope = emit_event(
        AMENDED_EVENT_NAME,
        event_kind="workflow",
        event_type="item_posture_amendment",
        source_type="system",
        session_id=session_id,
        severity="INFO",
        outcome="completed",
        project=project,
        item_id=item_id,
        context=context,
        conn=conn,
        transactional=True,
    )
    return envelope.event_id if envelope.ok else None


__all__ = ["AMENDED_EVENT_NAME", "emit_posture_amended"]
