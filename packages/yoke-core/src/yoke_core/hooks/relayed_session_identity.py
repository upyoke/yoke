"""One session-identity gate for every relayed hook payload.

Both the hook-evaluate route and the observation-batch route decide the
same question — may this payload's ``session_id`` act as a Yoke session? —
so they ask it here rather than each carrying its own predicate. They did
carry their own, and the two disagreed: evaluate accepted an
identity-stamped payload unconditionally while the batch route also ran
the conversation-alias shape check, so the identical payload was allowed
through one door and refused with HTTP 400 at the other.

The disagreement was not a tie. Only the client can answer the question,
because only the client can read this machine's cursor-session-map, and
that map legitimately records a Cursor conversation as its own session
(``record_conversation_session(conv, conv)`` for a non-worktree
workspace). For such a session the canonical id *equals* the conversation
alias, so a server-side shape test reports "conversation-shaped" for a
perfectly canonical id and has no way to tell it from a raw alias. The
client already refuses the raw case before it can be stamped: an unmapped
conversation folds to empty, and an empty fold never sets
``identity_stamped``. So a stamped payload has passed the only authority
that exists, and the shape test is applied to unstamped payloads only.

Trusting the stamp is not the whole answer, which is why
:func:`session_ownership_refusal` exists: a caller may still stamp a
session id belonging to somebody else. That check reads the authoritative
``harness_sessions`` row and requires it to belong to the authenticated
actor, matching how completed client-wall reports are authorized. It is
applied on the batch route, whose refusal costs one disposable telemetry
batch. The evaluate route keeps its existing project authorization
instead: a false refusal there blocks a live tool call on every machine at
once, and this module's job is to end one such fleet-wide refusal, not to
open a second one.
"""

from __future__ import annotations

from typing import Any, Mapping

from yoke_contracts.payload_session_fold import is_conversation_shaped_session_id


IDENTITY_MISSING = "identity_missing"
IDENTITY_CONVERSATION_SHAPED = "identity_conversation_shaped"

_REFUSAL_TEXT = {
    IDENTITY_MISSING: (
        "payload has no stamped, non-conversation session id; run the hook "
        "through `yoke hook evaluate`, which stamps ambient session identity"
    ),
    IDENTITY_CONVERSATION_SHAPED: (
        "session id is still conversation-shaped; the conversation has no "
        "recorded session on this machine, so re-run once the Cursor session "
        "map has paired it"
    ),
}


def stamped_identity_refusal(payload: Mapping[str, Any]) -> str | None:
    """Name why *payload*'s session id may not act, or ``None`` to accept."""
    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not session_id.strip():
        return IDENTITY_MISSING
    if payload.get("identity_stamped") is True:
        return None
    if is_conversation_shaped_session_id(payload, session_id=session_id):
        return IDENTITY_CONVERSATION_SHAPED
    return None


def refusal_text(reason: str) -> str:
    """Render one refusal with the recovery step its reader needs."""
    return _REFUSAL_TEXT.get(reason, _REFUSAL_TEXT[IDENTITY_MISSING])


def session_ownership_refusal(
    conn: Any,
    session_id: str,
    actor_id: int | None,
) -> str | None:
    """Refuse a stamped id whose existing session belongs to another actor.

    An id with no session row yet is accepted: the observation itself is
    what registers a session that a hook has only just started stamping.
    """
    if actor_id is None or not session_id:
        return None
    from yoke_core.domain import db_backend

    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        f"SELECT actor_id FROM harness_sessions WHERE session_id = {marker}",
        (session_id,),
    ).fetchone()
    if row is None:
        return None
    stored = row.get("actor_id") if isinstance(row, dict) else row[0]
    if stored is None or int(stored) == int(actor_id):
        return None
    return (
        "stamped session id belongs to a different actor; relay through the "
        "connection whose actor owns the session"
    )


__all__ = [
    "IDENTITY_CONVERSATION_SHAPED",
    "IDENTITY_MISSING",
    "refusal_text",
    "session_ownership_refusal",
    "stamped_identity_refusal",
]
