"""Durable message facts for stale-session sweep tests."""

from datetime import timedelta
from uuid import uuid4

from yoke_core.domain.session_message_store import insert_message
from yoke_core.domain.session_message_types import ResolvedRecipient, utc_now


def pending_message(conn, session_id):
    now = utc_now()
    project = conn.execute("SELECT slug FROM projects WHERE id=1").fetchone()[0]
    message, inserted = insert_message(
        conn,
        sender_actor_id=None,
        sender_session_id=None,
        sender_surface="cli",
        body="Report identity and reply.",
        selector_snapshot={},
        idempotency_key=None,
        created_at=now,
        expires_at=now + timedelta(hours=1),
        recipients=[
            ResolvedRecipient(
                session_id=session_id,
                project_id=1,
                project=project,
                executor="claude-code",
                executor_surface="claude-cli",
                executor_version=None,
                machine_id=None,
                liveness="stale",
                messageability={"messageable": True},
            )
        ],
        actor_recipients=[],
        wake_after_by_owner={("project", 1): now},
    )
    assert inserted
    conn.commit()
    return message["message_id"]


def start_message_attempt(conn, message_id, session_id, *, kind, started_at):
    conn.execute(
        "INSERT INTO session_message_attempts "
        "(attempt_id, message_id, target_session_id, attempt_kind, started_at, evidence) "
        "VALUES (%s, %s, %s, %s, %s, '{}')",
        (str(uuid4()), message_id, session_id, kind, started_at),
    )


def message_receipt(conn, message_id):
    return conn.execute(
        "SELECT state, acknowledged_at FROM session_message_recipients WHERE message_id=%s",
        (message_id,),
    ).fetchone()
