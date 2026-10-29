"""Insert one durable learning-log entry."""

from datetime import datetime
from typing import Optional
from yoke_contracts.field_note_text import KIND_VALUES
from yoke_contracts.timestamps import parse_instant, utc_now
from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import instant_parameter
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
    actor_id: Optional[int] = None,
    reporter_email: Optional[str] = None,
    yoke_version: Optional[str] = None,
    universe_fingerprint: Optional[str] = None,
) -> str:
    timestamp = instant_parameter(conn, parse_instant(timestamp))
    p = _p(conn)
    project_id = resolve_project_id(conn, project) if project else None
    target_project_id = (
        resolve_project_id(conn, target_project) if target_project else None
    )
    if category not in KIND_VALUES:
        raise ValueError("feedback_category_invalid: use failed, new, unclear, observation or idea")
    if not body.strip() or len(body) > 4000:
        raise ValueError("feedback_evidence_invalid: provide 1 to 4000 characters of evidence")

    # Native id read: driver-side generated-id attributes are fragile to
    # intervening sequence touches. RETURNING is the unambiguous form.
    row = conn.execute(
        "INSERT INTO ouroboros_entries "
        "(timestamp, agent, context, category, body, project_id, "
        "target_project_id, created_at, correlation_id, session_id, actor_id, reporter_email, yoke_version, universe_fingerprint) "
        f"VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}) RETURNING id",
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
            actor_id,
            reporter_email,
            yoke_version,
            universe_fingerprint,
        ),
    ).fetchone()
    conn.commit()
    return str(row[0])
