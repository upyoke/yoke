"""Session actor resolution for native event emission.

Kept out of ``events.py`` so the emitter stays under Yoke's authored-file
line cap while still owning the single runtime contract: session-bound events
inherit ``harness_sessions.actor_id`` when the event did not explicitly carry
an actor. The same lookup doubles as the provenance gate — an event whose
session id has no ``harness_sessions`` row at all is marked
``provenance_unverified`` in its context so unregistered-session writes are
recorded, never silently trusted. The marking rides the lookup that already
runs (zero extra queries for registered sessions).
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from yoke_core.domain import db_backend


PROVENANCE_UNVERIFIED_KEY = "provenance_unverified"


def apply_session_actor_id(
    envelope: Dict[str, Any],
    *,
    db_path: Optional[str] = None,
    conn: Optional[Any] = None,
) -> None:
    """Populate actor_id from harness_sessions for session-bound events.

    When the lookup positively finds no ``harness_sessions`` row for the
    envelope's session id, the envelope context gains
    ``provenance_unverified: true``. A lookup that could not run (DB
    error) marks nothing — only a positive no-row finding may flag.
    """
    if envelope.get("actor_id") is not None:
        return
    session_id = str(envelope.get("session_id") or "").strip()
    if not session_id or session_id == "unknown":
        return
    if conn is not None:
        found, actor_id = session_actor_lookup(conn, session_id)
    else:
        own_conn = db_backend.connect(db_path)
        try:
            found, actor_id = session_actor_lookup(own_conn, session_id)
        finally:
            own_conn.close()
    if actor_id is not None:
        envelope["actor_id"] = actor_id
    if found is False:
        _mark_provenance_unverified(envelope)


def _mark_provenance_unverified(envelope: Dict[str, Any]) -> None:
    context = envelope.get("context")
    if isinstance(context, dict):
        context.setdefault(PROVENANCE_UNVERIFIED_KEY, True)
    else:
        envelope["context"] = {PROVENANCE_UNVERIFIED_KEY: True}


def session_actor_lookup(
    conn: Any, session_id: str
) -> Tuple[Optional[bool], Optional[int]]:
    """Return ``(row_found, actor_id)`` for ``session_id``; never raises.

    ``row_found`` is ``True`` when a ``harness_sessions`` row exists,
    ``False`` on a positive no-row finding, and ``None`` when the lookup
    failed (so callers can distinguish "unregistered" from "unknown").
    """
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    savepoint = "_yoke_event_actor_lookup"
    savepoint_created = False
    try:
        if db_backend.connection_is_postgres(conn):
            conn.execute(f"SAVEPOINT {savepoint}")
            savepoint_created = True
        row = conn.execute(
            f"SELECT actor_id FROM harness_sessions WHERE session_id = {p}",
            (session_id,),
        ).fetchone()
        if savepoint_created:
            conn.execute(f"RELEASE SAVEPOINT {savepoint}")
    except db_backend.database_error_types(conn):
        if savepoint_created:
            try:
                conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                conn.execute(f"RELEASE SAVEPOINT {savepoint}")
            except Exception:
                pass
        return None, None
    if row is None:
        return False, None
    raw = row.get("actor_id") if hasattr(row, "get") else row[0]
    if raw in (None, ""):
        return True, None
    try:
        return True, int(raw)
    except (TypeError, ValueError):
        return True, None
