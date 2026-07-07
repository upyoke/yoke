"""Bulk release of every active claim for a session.

Sibling of :mod:`sessions_lifecycle_release`. The typed per-claim
release path (``release_work_claim_for_execution``) clears
``harness_sessions.current_item_id`` when the released claim's item
matches focus; the by-claim-id sibling (``release_claim_by_id``) was
brought to parity earlier. This bulk path is the third member of the
family: callers ask "release every claim this session holds" without
ending the session (HTTP ``POST /sessions/{id}/release-all``, the legacy
``release-all-claims`` CLI). After such a release, any retained item
focus is structurally stale, so we clear it before commit. The
destructive ``--release-claims`` SessionEnd branch is unaffected —
``end_session`` follows the bulk release with a session-wide clear at
the wrapper layer.
"""

from __future__ import annotations

from typing import Any

from .claim_chain_state import record_release_intent_for_session
from .sessions_queries import _now_iso
from .sessions_render_attribution import clear_current_item


def release_all_claims(
    conn: Any,
    session_id: str,
    reason: str = "released",
) -> int:
    """Release all active claims for a session.  Returns count released."""
    now = _now_iso()
    cursor = conn.execute(
        """UPDATE work_claims SET released_at = %s, release_reason = %s
           WHERE session_id = %s AND released_at IS NULL""",
        (now, reason, session_id),
    )
    record_release_intent_for_session(
        conn, session_id=session_id, released_at=now, intent=reason,
    )
    clear_current_item(conn, session_id)
    conn.commit()
    return cursor.rowcount


__all__ = ["release_all_claims"]
