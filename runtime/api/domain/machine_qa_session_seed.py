"""Session seeding for machine-QA fixtures.

A coordination claim reads its actor from the session row that holds it,
so a fixture that never registers the acting session issues a claim with
no actor and every owner check on the submit side refuses it. Kept apart
from the rest of the machine-QA support so the schema fixture stays the
subject of its own module.
"""

from __future__ import annotations

from typing import Any

from yoke_contracts.timestamps import parse_instant
from yoke_core.domain.db_helpers import instant_parameter, utc_now


def seed_qa_session(
    conn: Any, *session_ids: str, actor_id: int = 1, messageable: bool = False
) -> None:
    """Register the sessions a host-control execution claims the host as.

    A coordination claim reads its actor from the session row that holds
    it, so a fixture that never registers the session issues a claim with
    no actor and every owner check on the submit side refuses it. Works on
    both the minimal sqlite fixture and the full Postgres schema.
    """
    from yoke_core.domain import db_backend

    if db_backend.connection_is_postgres(conn):
        seeded_at = instant_parameter(conn, parse_instant("2026-08-01T00:00:00Z"))
        for session_id in session_ids:
            conn.execute(
                "INSERT INTO harness_sessions "
                "(session_id, executor, provider, model, execution_level, "
                "workspace, project_id, mode, offered_at, last_heartbeat, "
                "actor_id) VALUES (%s, 'codex', 'openai', 'test-model', "
                "NULL, %s, 1, 'wait', %s, %s, %s) "
                "ON CONFLICT (session_id) DO NOTHING",
                (
                    session_id,
                    f"/tmp/{session_id}",
                    seeded_at,
                    seeded_at,
                    actor_id,
                ),
            )
    else:
        for session_id in session_ids:
            conn.execute(
                "INSERT OR IGNORE INTO harness_sessions"
                "(session_id,actor_id,executor,last_heartbeat) "
                "VALUES(?,?,'codex',?)",
                (session_id, actor_id, instant_parameter(conn, utc_now())),
            )
    if messageable:
        from yoke_contracts.session_control.capabilities import capability_for_surface
        from yoke_core.domain.actor_permissions import (
            ROLE_OPERATOR,
            grant_actor_project_role,
            seed_roles_and_permissions,
        )

        seed_roles_and_permissions(conn)
        grant_actor_project_role(
            conn, actor_id=actor_id, project_id=1, role_name=ROLE_OPERATOR
        )
        p = "%s" if db_backend.connection_is_postgres(conn) else "?"
        for session_id in session_ids:
            conn.execute(
                f"UPDATE harness_sessions SET executor_surface={p},executor_version={p} "
                f"WHERE session_id={p}",
                (
                    "codex-cli",
                    capability_for_surface("codex-cli").minimum_version,
                    session_id,
                ),
            )
    conn.commit()


def seed_registered_qa_launch(
    conn: Any,
    session_id: str,
    *,
    requester_session_id: str | None = None,
    key: str | None = None,
    actor_id: int = 1,
) -> str:
    """Record the real launch and opening message rows for a fixture worker."""
    from datetime import timedelta
    from uuid import uuid4

    from yoke_core.domain.session_launch_store import insert_instruction_message

    def worker_row():
        return conn.execute(
            "SELECT actor_id, project_id FROM harness_sessions WHERE session_id=%s",
            (session_id,),
        ).fetchone()

    worker = worker_row()
    if worker is None:
        seed_qa_session(conn, session_id, actor_id=actor_id)
        worker = worker_row()
    launch_key = key or f"qa-walk:PLAN@SHA:-:{session_id}:1"
    existing = conn.execute(
        "SELECT launch_id FROM session_launches WHERE registered_session_id=%s "
        "AND idempotency_key=%s AND item_id IS NULL",
        (session_id, launch_key),
    ).fetchone()
    if existing:
        return str(existing[0])
    requester = requester_session_id or f"{session_id}-launcher"
    now = utc_now()
    conn.execute(
        "INSERT INTO actors (id, kind, created_at) VALUES (%s, 'human', %s) "
        "ON CONFLICT (id) DO NOTHING",
        (worker["actor_id"], now),
    )
    if requester_session_id is None:
        seed_qa_session(conn, requester, actor_id=worker["actor_id"])
    launch_id = str(uuid4())
    message_id = str(uuid4())
    deadline = now + timedelta(minutes=10)
    insert_instruction_message(
        conn,
        message_id=message_id,
        launch_id=launch_id,
        actor_id=worker["actor_id"],
        session_id=requester,
        sender_surface=None,
        project_id=worker["project_id"],
        body="Walk QA.",
        created_at=now,
        expires_at=deadline,
    )
    conn.execute(
        "INSERT INTO session_launches (launch_id,requester_actor_id,"
        "requester_session_id,project_id,requested_surface,selected_surface,"
        "message_id,idempotency_key,state,registered_session_id,created_at,deadline_at) "
        "VALUES (%s,%s,%s,%s,'codex-cli','codex-cli',%s,%s,'succeeded',%s,%s,%s)",
        (launch_id, worker["actor_id"], requester, worker["project_id"],
         message_id, launch_key, session_id, now, deadline),
    )
    conn.execute(
        "UPDATE harness_sessions SET first_completed_work_at=%s WHERE session_id=%s",
        (now, session_id),
    )
    conn.commit()
    return launch_id


__all__ = ["seed_qa_session", "seed_registered_qa_launch"]
