"""Event emission for path-claim dependency refreshes."""

from __future__ import annotations

from typing import Any, Optional


def emit_blocked_reason_refreshed(
    conn: Any,
    *,
    claim_id: int,
    item_id: Optional[int],
    prior_blocked_reason: str,
    new_blocked_reason: str,
    released_claim_id: int,
) -> None:
    """Best-effort telemetry for a surviving dependency blocker."""
    try:
        from yoke_core.domain.events import emit_event as native_emit
    except ImportError:
        return
    from yoke_core.domain.session_ambient_identity import (
        resolve_ambient_session_id,
    )

    session_id = resolve_ambient_session_id() or ""
    try:
        native_emit(
            "PathClaimBlockedReasonRefreshed",
            event_kind="lifecycle",
            event_type="path_claim",
            source_type="system",
            session_id=session_id,
            severity="INFO",
            outcome="completed",
            project="yoke",
            item_id=item_id,
            context={
                "claim_id": claim_id,
                "prior_blocked_reason": prior_blocked_reason,
                "new_blocked_reason": new_blocked_reason,
                "released_claim_id": released_claim_id,
            },
            conn=conn,
        )
    except Exception:
        return


__all__ = ["emit_blocked_reason_refreshed"]
