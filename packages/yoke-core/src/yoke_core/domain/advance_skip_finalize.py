"""Event and claim finalization helpers for advance skip flows."""

from __future__ import annotations

from yoke_core.domain.session_ambient_identity import resolve_ambient_session_id
from yoke_core.domain.project_identity_item_ref import item_ref_for_id

from typing import Optional, TextIO


def _resolve_session_id(session_id: Optional[str] = None) -> Optional[str]:
    if session_id:
        return session_id
    return resolve_ambient_session_id()


def _emit_skip_event(
    item_id: int,
    *,
    via: str,
    from_status: str,
    to_status: str,
    skipped_phase: str,
    out: TextIO,
) -> None:
    """Emit a ``SkipHopPerformed`` lifecycle event carrying skip metadata."""
    try:
        from yoke_core.domain.events import emit_event
    except ImportError:
        print(
            f"Warning: SkipHopPerformed event emission skipped for "
            f"{item_ref_for_id(item_id)}"
            " (events module unavailable)",
            file=out,
        )
        return

    envelope = emit_event(
        "SkipHopPerformed",
        event_kind="lifecycle",
        event_type="status",
        source_type="system",
        severity="STATUS",
        outcome="completed",
        item_id=item_id,
        context={
            "from_status": from_status,
            "to_status": to_status,
            "via": via,
            "skipped_phase": skipped_phase,
            "operator_assertion": True,
        },
    )
    if not envelope.ok:
        print(
            f"Warning: SkipHopPerformed event emission failed for "
            f"{item_ref_for_id(item_id)}",
            file=out,
        )


def _release_claim(
    item_id: int,
    *,
    reason: str,
    session_id: Optional[str],
    out: TextIO,
) -> dict:
    """Release the current session's claim on *item_id* with *reason*."""
    effective_session_id = _resolve_session_id(session_id)
    if not effective_session_id:
        return {"released": False, "reason": "missing_session_id"}

    try:
        from yoke_core.domain.db_helpers import connect
        from yoke_core.domain.project_identity import render_item_ref
        from yoke_core.domain.sessions import release_item_claim_for_execution

        with connect() as conn:
            result = release_item_claim_for_execution(
                conn, effective_session_id, str(item_id), reason
            )
            public_ref = render_item_ref(conn, item_id)
    except Exception as exc:
        return {"released": False, "reason": "exception", "error": str(exc)}

    if result.get("released"):
        print(f"Claim released: {public_ref} (reason={reason})", file=out)
    return result
