"""Event-row INSERT path for the non-fatal Python emitter.

Owns ``_write_event``: the connection-vs-short-lived-connect branch that
turns a built envelope into a row in the ``events`` table. Kept separate
from :mod:`yoke_core.domain.events` so the emitter module stays within the
authored-file line cap.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from . import db_backend
from .events_insert_sql import _INSERT_SQL
from .events_project_identity import resolve_envelope_project_id_for_event
from .events_session_actor import apply_session_actor_id
from .events_write_conn import event_insert_params, write_event_row_on_conn


def _write_event(
    envelope: Dict[str, Any],
    *,
    db_path: Optional[str] = None,
    conn: Optional[Any] = None,
) -> bool:
    """Insert an event row into the events table.

    If ``conn`` is provided, uses it directly (caller manages lifecycle).
    Otherwise opens a short-lived connection to the resolved DB path.
    """
    if conn is not None:
        apply_session_actor_id(envelope, conn=conn)
        project_id = resolve_envelope_project_id_for_event(conn, db_path, envelope)
        return write_event_row_on_conn(
            conn, _INSERT_SQL, event_insert_params(envelope, project_id)
        )

    own_conn = db_backend.connect(db_path)
    try:
        apply_session_actor_id(envelope, conn=own_conn)
        project_id = resolve_envelope_project_id_for_event(own_conn, db_path, envelope)
        wrote = write_event_row_on_conn(
            own_conn, _INSERT_SQL, event_insert_params(envelope, project_id)
        )
        own_conn.commit()
        return wrote
    finally:
        own_conn.close()


__all__ = ["_write_event"]
