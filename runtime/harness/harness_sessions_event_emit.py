"""Event emission helpers for harness_sessions / work_claims mutations.

Owns the small surface that translates a context payload (often JSON)
plus optional item/task identifiers into a uniform ``emit_event`` call
keyed by ``session_lifecycle``. Kept separate from focus-tracking so
the write paths do not need to import event-emission internals when
they only need preconditions or focus rotation.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional


def _coerce_task_num(raw: Any) -> Optional[int]:
    """Return an integer task number when *raw* is parseable."""
    if raw in (None, ""):
        return None
    try:
        return int(str(raw))
    except (TypeError, ValueError):
        return None


def _parse_detail(context: str) -> Dict[str, Any]:
    """Parse a JSON detail payload, tolerating malformed historical inputs."""
    if not context:
        return {}
    try:
        parsed = json.loads(context)
    except json.JSONDecodeError:
        return {"_raw_context": context}
    if isinstance(parsed, dict):
        return parsed
    return {"_raw_context": parsed}


def _emit_event(
    conn,
    session_id: str,
    event_name: str,
    context: str,
    *,
    item_id: Optional[str] = None,
    task_num: Optional[int] = None,
) -> None:
    """Best-effort event emission via the native Python event emitter."""
    detail = _parse_detail(context)
    resolved_item = item_id
    if resolved_item is None:
        if detail.get("item_id") not in (None, ""):
            resolved_item = str(detail["item_id"])
        elif detail.get("epic_id") not in (None, ""):
            resolved_item = str(detail["epic_id"])
    resolved_task = task_num
    if resolved_task is None:
        resolved_task = _coerce_task_num(detail.get("task_num"))
    try:
        from yoke_core.domain.events import emit_event

        emit_event(
            event_name,
            event_kind="system",
            event_type="session_lifecycle",
            source_type="backend",
            severity="INFO",
            outcome="completed",
            session_id=session_id,
            item_id=resolved_item,
            task_num=resolved_task,
            context={"detail": detail},
            conn=conn,
        )
    except Exception:
        pass
