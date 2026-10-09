"""Transactional event append for decision-request mutations."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Optional

from yoke_contracts.timestamps import parse_instant

from yoke_core.domain import db_backend
from yoke_core.domain.events import build_envelope
from yoke_core.domain.events_insert_sql import _INSERT_SQL
from yoke_core.domain.events_retired_name_guard import (
    assert_event_name_not_retired,
)
from yoke_core.domain.events_write_conn import (
    event_insert_params,
    write_event_row_on_conn,
)


def append_decision_event(
    conn: Any,
    event_name: str,
    *,
    actor_id: Optional[int],
    session_id: str,
    project_id: Optional[int],
    org_id: Optional[int],
    context: Mapping[str, Any],
    created_at: datetime | str,
) -> str:
    """Append an event and return its id without committing."""
    stamp = parse_instant(created_at)
    # An event whose request names no project says so; naming one at
    # random makes a row that reads like a deliberate attribution.
    project = ""
    if project_id is not None:
        p = "%s" if db_backend.connection_is_postgres(conn) else "?"
        row = conn.execute(
            f"SELECT slug FROM projects WHERE id = {p}",
            (project_id,),
        ).fetchone()
        if row is not None:
            project = str(row[0])
    envelope = build_envelope(
        event_name,
        event_kind="lifecycle",
        event_type="decision_request",
        source_type="backend",
        session_id=session_id,
        org_id=str(org_id) if org_id is not None else None,
        project=project,
        agent=str(actor_id) if actor_id is not None else "engine",
        context=dict(context),
        created_at=stamp,
    )
    envelope["actor_id"] = actor_id
    if db_backend.connection_is_postgres(conn):
        assert_event_name_not_retired(conn, event_name)
    write_event_row_on_conn(
        conn, _INSERT_SQL, event_insert_params(envelope, project_id)
    )
    return str(envelope["event_id"])


__all__ = ["append_decision_event"]
