"""Session seeding for machine-QA fixtures.

A coordination claim reads its actor from the session row that holds it,
so a fixture that never registers the acting session issues a claim with
no actor and every owner check on the submit side refuses it. Kept apart
from the rest of the machine-QA support so the schema fixture stays the
subject of its own module.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.db_helpers import iso8601_now


def seed_qa_session(
    conn: Any, *session_ids: str, actor_id: int = 2, messageable: bool = False
) -> None:
    """Register the sessions a host-control execution claims the host as.

    A coordination claim reads its actor from the session row that holds
    it, so a fixture that never registers the session issues a claim with
    no actor and every owner check on the submit side refuses it. Works on
    both the minimal sqlite fixture and the full Postgres schema.
    """
    from yoke_core.domain import db_backend

    if db_backend.connection_is_postgres(conn):
        for session_id in session_ids:
            conn.execute(
                "INSERT INTO harness_sessions "
                "(session_id, executor, provider, model, execution_lane, "
                "workspace, project_id, mode, offered_at, last_heartbeat, "
                "actor_id) VALUES (%s, 'codex', 'openai', 'test-model', "
                "'primary', %s, 1, 'wait', %s, %s, %s) "
                "ON CONFLICT (session_id) DO NOTHING",
                (
                    session_id,
                    f"/tmp/{session_id}",
                    "2026-08-01T00:00:00Z",
                    "2026-08-01T00:00:00Z",
                    actor_id,
                ),
            )
    else:
        for session_id in session_ids:
            conn.execute(
                "INSERT OR IGNORE INTO harness_sessions"
                "(session_id,actor_id,executor,last_heartbeat) "
                "VALUES(?,?,'codex',?)",
                (session_id, actor_id, iso8601_now()),
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


__all__ = ["seed_qa_session"]
