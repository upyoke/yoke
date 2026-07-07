"""Session-scoped release of every active work-claim held by the caller.

Companion to :mod:`claims_work` (per-claim release via ``claims.work.release``)
and the no-flags ``session-end`` auto-release helper in
:mod:`sessions_render_end_claim_release`. The agent surface needed one
positive primitive for "release every claim THIS session still holds,
but do NOT end the session" — the harness owns session lifetime.

The function walks ``work_claims`` for the calling ``session_id`` (strict
same-session filter, no parent-session cascade — see below) and reuses
:func:`sessions_render_end_claim_release.release_session_claims` so item,
epic_task, and process targets all go through the canonical per-row
release path (events, audit, linked path-claim cascade).

Cascade isolation:
    The parent-session cascade resolves the AUTHORITATIVE session for
    claim verification on the read path. Here we are mutating claims and
    must use the literal calling session id, never the cascade. A Codex
    subagent calling ``--all-mine`` releases ONLY its own session's
    claims; the parent's claims stay held.
"""

from __future__ import annotations

from typing import Any, Dict

from . import db_backend, db_helpers
from .sessions_render_end_claim_release import (
    AGENT_HANDOFF_RELEASE_VIA,
    release_session_claims,
)


AGENT_HANDOFF_RELEASE_REASON = "agent_handoff_session_scoped"


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def release_all_claims_for_session(session_id: str) -> Dict[str, Any]:
    """Release every active work-claim held by ``session_id``.

    Returns a dict with ``released_count`` and ``released_claims`` (the
    JSON-safe per-claim payload from
    :func:`release_session_claims`). Zero-effect when the session holds
    no active claims (returns ``{"released_count": 0,
    "released_claims": []}``).

    Implementation reuses :func:`release_session_claims` rather than
    re-implementing the per-row loop, ensuring event emission,
    audit, process-owned path-claim cascade, and target-kind semantics
    stay consistent with the no-flags ``session-end`` branch. The only
    operator-visible difference is the release-reason intent:
    ``agent_handoff_session_scoped`` is preserved on each
    ``WorkReleased`` event's ``release_reason_intent`` field and on the
    aggregate ``HarnessSessionEndReleasedClaims`` envelope (via
    ``context.release_reason`` and ``context.via``) so audit callers can
    distinguish session-end auto-release from agent-driven handoff. The
    schema-enum value stored in ``work_claims.release_reason`` remains
    ``handed_off`` per the CHECK constraint — the canonical map lives in
    :data:`sessions_lifecycle_release._RELEASE_REASON_SCHEMA_MAP`.

    Strict same-session filter: the ``WHERE session_id = ?`` clause uses
    the literal calling ``session_id``, never the parent-session cascade
    resolver. A subagent calling this primitive releases its own claims
    only; the parent session's claims remain held.
    """
    if not session_id:
        return {"released_count": 0, "released_claims": []}

    with db_helpers.connect() as conn:
        p = _p(conn)
        active_rows = conn.execute(
            f"""SELECT id, target_kind, item_id, epic_id, task_num,
                       process_key, conflict_group
                FROM work_claims
                WHERE session_id = {p} AND released_at IS NULL
                ORDER BY claimed_at ASC, id ASC""",
            (session_id,),
        ).fetchall()

        if not active_rows:
            return {"released_count": 0, "released_claims": []}

        released = release_session_claims(
            conn,
            session_id,
            active_claim_rows=active_rows,
            release_reason=AGENT_HANDOFF_RELEASE_REASON,
            via=AGENT_HANDOFF_RELEASE_VIA,
        )

    return {
        "released_count": len(released),
        "released_claims": released,
    }


__all__ = [
    "AGENT_HANDOFF_RELEASE_REASON",
    "release_all_claims_for_session",
]
