"""Insert one durable learning-log entry."""

from datetime import datetime
from typing import Optional
from yoke_contracts.timestamps import parse_instant, utc_now
from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import instant_parameter, query_one
from yoke_core.domain.project_identity import resolve_project_id


def _p(conn):
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def cmd_insert_entry(
    conn,
    timestamp: datetime | str,
    agent: str,
    context: Optional[str],
    category: str,
    body: str,
    project: Optional[str] = None,
    target_project: Optional[str] = None,
    correlation_id: Optional[int] = None,
    session_id: Optional[str] = None,
) -> str:
    timestamp = instant_parameter(conn, parse_instant(timestamp))
    p = _p(conn)
    project_id = resolve_project_id(conn, project) if project else None
    target_project_id = (
        resolve_project_id(conn, target_project) if target_project else None
    )
    existing = query_one(
        conn,
        "SELECT id FROM ouroboros_entries "
        f"WHERE timestamp={p} AND agent={p} AND category={p} AND body={p}",
        (timestamp, agent, category, body),
    )
    if existing:
        return "Duplicate entry skipped"

    # Native id read: driver-side generated-id attributes are fragile to
    # intervening sequence touches. RETURNING is the unambiguous form.
    row = conn.execute(
        "INSERT INTO ouroboros_entries "
        "(timestamp, agent, context, category, body, project_id, "
        "target_project_id, created_at, correlation_id, session_id) "
        f"VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}) RETURNING id",
        (
            timestamp,
            agent,
            context,
            category,
            body,
            project_id,
            target_project_id,
            instant_parameter(conn, utc_now()),
            correlation_id,
            session_id,
        ),
    ).fetchone()
    conn.commit()
    return str(row[0])
