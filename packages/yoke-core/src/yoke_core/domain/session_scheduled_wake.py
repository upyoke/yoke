"""Timed self-wakes become Fleet messages only when their due instant arrives."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from yoke_contracts.session_control.models import RecipientSelector
from yoke_contracts.timestamps import format_instant, parse_instant
from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import instant_parameter
from yoke_core.domain.db_savepoint import savepoint
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.session_explicit_wake import mark_explicit_stopped_wake
from yoke_core.domain.session_message_service import send_message
from yoke_core.domain.session_message_types import SessionMessageError, utc_now
from yoke_core.hooks.relayed_session_identity import session_ownership_refusal


def schedule_session_wake(
    conn: Any,
    *,
    session_id: str,
    actor_id: int,
    at: datetime,
    reason: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Store one self-addressed timed wake without changing the session's park."""
    current = parse_instant(now or utc_now())
    due = parse_instant(at)
    if due <= current or not reason.strip():
        raise SessionMessageError(
            "scheduled_wake_invalid",
            "Choose a future --at instant with a UTC offset and a nonempty --reason, "
            "then run yoke sessions wake schedule again.",
        )
    refusal = session_ownership_refusal(conn, session_id, actor_id)
    if refusal:
        raise SessionMessageError("scheduled_wake_forbidden", refusal)
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    wake_id = str(uuid4())
    with savepoint(conn, "_schedule_session_wake", owns=False):
        cursor = conn.execute(
            "INSERT INTO session_scheduled_wakes "
            "(wake_id,session_id,actor_id,due_at,reason,created_at) "
            f"VALUES ({','.join([p] * 6)}) "
            "ON CONFLICT(session_id,due_at,reason) DO NOTHING",
            (
                wake_id,
                session_id,
                actor_id,
                instant_parameter(conn, due),
                reason.strip(),
                instant_parameter(conn, current),
            ),
        )
        created = cursor.rowcount == 1
        row = conn.execute(
            f"SELECT wake_id FROM session_scheduled_wakes WHERE session_id={p} "
            f"AND due_at={p} AND reason={p}",
            (session_id, instant_parameter(conn, due), reason.strip()),
        ).fetchone()
    return {
        "wake_id": str(row[0]),
        "scheduled_at": format_instant(due),
        "deduplicated": not created,
    }


def enqueue_due_session_wakes(conn: Any, *, now: datetime) -> int:
    """The existing relay sweep atomically consumes due timers once.

    Older serving processes cannot see pending timers as messages. Each due
    timer creates an ordinary explicit wake; existing delivery owns retries.
    A missing table is possible only in lean fixtures or pre-convergence reads.
    """
    if not _table_exists(conn, "session_scheduled_wakes"):
        return 0
    postgres = db_backend.connection_is_postgres(conn)
    p = "%s" if postgres else "?"
    lock = " FOR UPDATE OF sw SKIP LOCKED" if postgres else ""
    rows = conn.execute(
        "SELECT sw.* FROM session_scheduled_wakes sw "
        "JOIN harness_sessions hs ON hs.session_id=sw.session_id "
        f"WHERE sw.message_id IS NULL AND sw.due_at<={p} "
        "AND hs.terminated_at IS NULL ORDER BY sw.due_at,sw.wake_id LIMIT 100" + lock,
        (instant_parameter(conn, now),),
    ).fetchall()
    for row in rows:
        with savepoint(conn, "_enqueue_scheduled_wake", owns=False):
            sent = send_message(
                conn,
                actor_id=int(row["actor_id"]),
                sender_session_id=None,
                engine_sender=True,
                selector=RecipientSelector(session_ids=[row["session_id"]]),
                body=f"Your timed recheck is due at {format_instant(parse_instant(row['due_at']))}: "
                f"{row['reason']}. Read the current requirement and evidence before resuming work.",
                idempotency_key=f"scheduled-wake:{row['wake_id']}",
                now=now,
                commit=False,
            )
            message_id = str(sent["message_id"])
            mark_explicit_stopped_wake(
                conn, message_id=message_id, session_id=row["session_id"]
            )
            conn.execute(
                f"UPDATE session_scheduled_wakes SET message_id={p} WHERE wake_id={p}",
                (message_id, row["wake_id"]),
            )
    return len(rows)
