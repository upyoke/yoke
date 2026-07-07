"""Short-lived own-connection event INSERT for the native emitter.

Extracted from :mod:`yoke_core.domain.events` to keep that module under the
file-line cap. Owns the branch the emitter takes when no caller-managed
connection is supplied: open a backend-appropriate connection, insert one
event row, commit, close.

Backend routing: when the Postgres backend is selected, route through
the shared backend factory (:func:`yoke_core.domain.db_backend.connect`) even
when a SQLite-style ``db_path`` token is passed. Postgres file-test helpers
repoint ``YOKE_PG_DSN`` and thread the same path token through unchanged; the
backend factory is the seam that maps it to the active disposable database.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional, Sequence

from yoke_core.domain import db_backend


def event_insert_params(
    envelope: Dict[str, Any],
    project_id: Optional[int],
) -> tuple[Any, ...]:
    envelope_json = json.dumps(envelope)
    return (
        envelope["event_id"],
        envelope["event_name"],
        envelope["event_kind"],
        envelope["event_type"],
        envelope["source_type"],
        envelope["session_id"],
        envelope["severity"],
        envelope.get("event_outcome"),
        envelope.get("user_id"),
        envelope.get("org_id"),
        envelope.get("environment"),
        envelope.get("service", "cli"),
        project_id,
        envelope.get("actor_id"),
        envelope.get("item_id"),
        envelope.get("task_num"),
        envelope.get("agent"),
        envelope.get("tool_name"),
        envelope.get("duration_ms"),
        envelope.get("exit_code"),
        envelope.get("trace_id"),
        envelope.get("parent_id"),
        envelope.get("anomaly_flags"),
        envelope.get("tool_use_id"),
        envelope.get("turn_id"),
        envelope.get("hook_event_name"),
        envelope_json,
        envelope["created_at"],
    )


def write_event_row(
    insert_sql: str,
    params: Sequence[Any],
    *,
    db_path: Optional[str] = None,
) -> bool:
    """Open a short-lived connection and insert one event row.

    Returns ``True`` when a row was inserted, ``False`` when no DB target could
    be resolved (the emitter treats this as a benign skip).
    """
    own_conn = db_backend.connect(db_path)
    try:
        own_conn.execute(insert_sql, params)
        own_conn.commit()
        return True
    finally:
        own_conn.close()


def write_event_row_on_conn(conn: Any, insert_sql: str, params: Sequence[Any]) -> bool:
    """Insert one event row on a caller-owned connection.

    Missing optional event tables are raised back to the native emitter, but the
    Postgres transaction state is restored before that best-effort failure is
    swallowed.
    """
    if not db_backend.connection_is_postgres(conn):
        insert_sql = insert_sql.replace("%s", "?")
    savepoint = "_yoke_event_write"
    use_savepoint = db_backend.connection_is_postgres(conn)
    savepoint_created = False
    try:
        if use_savepoint:
            conn.execute(f"SAVEPOINT {savepoint}")
            savepoint_created = True
        conn.execute(insert_sql, params)
        if use_savepoint:
            conn.execute(f"RELEASE SAVEPOINT {savepoint}")
        conn.commit()
        return True
    except db_backend.database_error_types(conn):
        if savepoint_created:
            try:
                conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                conn.execute(f"RELEASE SAVEPOINT {savepoint}")
            except Exception:
                pass
        raise
